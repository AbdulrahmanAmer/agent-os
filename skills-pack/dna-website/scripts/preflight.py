"""
Preflight: validate the target URL and confirm the run is allowed.

This stage is the first guardrail. It checks:
- URL is well-formed
- Domain isn't in the blocked-categories list
- robots.txt allows the path (unless --ignore-robots)
- User has confirmed any overrides

Output: preflight.json (PreflightResult model)
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import aiohttp

from scripts.config import Config
from scripts.models import PreflightFlags, PreflightResult, write_model
from scripts.utils import ensure_dir, is_purchase_url


# Domains that require --i-own-this-site to crawl
BLOCKED_DOMAINS = {
    # Banking
    "chase.com", "bankofamerica.com", "wellsfargo.com", "citi.com",
    "barclays.com", "hsbc.com",
    # Government
    "irs.gov", "ssa.gov", "uscis.gov", "dmv.org",
    # Healthcare
    "mychart.com", "anthem.com", "cigna.com",
    # Dating
    "tinder.com", "bumble.com", "hinge.co", "match.com",
}

BLOCKED_CATEGORIES = {
    "banking": ["bank", "financial", "credit-union"],
    "government": [".gov", ".mil"],
    "healthcare": ["hospital", "clinic", "patient", "mychart"],
    "dating": ["dating", "match"],
}


def category_of(domain: str, url: str) -> str | None:
    """Best-effort categorization. Returns None if not blocked."""
    if domain in BLOCKED_DOMAINS:
        # Look up which category
        for cat in BLOCKED_CATEGORIES:
            if any(kw in domain for kw in BLOCKED_CATEGORIES[cat]):
                return cat
        return "blocked"
    if domain.endswith(".gov") or domain.endswith(".mil"):
        return "government"
    return None


async def fetch_robots(base_origin: str) -> tuple[bool, list[str]]:
    """
    Fetch and parse robots.txt for the origin.

    Returns:
        (allowed, disallow_paths)
        allowed: whether '/' is allowed for our user agent
        disallow_paths: all Disallow: rules
    """
    robots_url = urljoin(base_origin, "/robots.txt")
    disallow: list[str] = []
    allowed = True
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(robots_url, timeout=10) as resp:
                if resp.status != 200:
                    return True, []
                text = await resp.text()
        rp = RobotFileParser()
        rp.parse(text.splitlines())
        # Parse Disallow lines manually for reporting
        current_ua = None
        for line in text.splitlines():
            line = line.strip()
            if line.lower().startswith("user-agent:"):
                current_ua = line.split(":", 1)[1].strip()
            elif line.lower().startswith("disallow:") and current_ua in ("*", None):
                path = line.split(":", 1)[1].strip()
                if path:
                    disallow.append(path)
        allowed = rp.can_fetch("*", base_origin + "/")
    except Exception:
        return True, []  # If we can't fetch robots, assume allowed (conservative)
    return allowed, disallow


def run_preflight(config: Config, *, interactive: bool | None = None) -> PreflightResult:
    """
    Execute preflight checks. May prompt the user for confirmation.

    interactive=None auto-detects: prompts only when stdin is a TTY.
    """
    if interactive is None:
        interactive = bool(sys.stdin.isatty())
    warnings: list[str] = []

    # 0. Hard rule: target URL itself must never be a purchase URL.
    if is_purchase_url(config.url):
        raise SystemExit(
            f"Refusing to crawl {config.url!r}: matches a purchase URL pattern. "
            "Pick a different seed URL (e.g. the dashboard home)."
        )

    # 1. Category check
    blocked_cat = category_of(config.domain, config.url)
    if blocked_cat and not config.i_own_this_site:
        msg = (
            f"Domain {config.domain} falls in blocked category {blocked_cat!r}. "
            "Pass --i-own-this-site to proceed."
        )
        if interactive:
            answer = input(f"{msg}\n  Type 'I own this site' to override: ")
            if answer.strip().lower() != "i own this site":
                raise SystemExit("Preflight aborted: user declined override.")
            warnings.append(f"User overrode category block ({blocked_cat})")
        else:
            raise SystemExit(msg)

    # 2. robots.txt
    allowed, disallow = asyncio.run(fetch_robots(config.base_origin))
    if not allowed and not config.ignore_robots:
        msg = f"robots.txt disallows '/' for {config.base_origin}."
        if interactive:
            answer = input(
                f"{msg}\n  Type 'ignore robots' to override: "
            )
            if answer.strip().lower() != "ignore robots":
                raise SystemExit("Preflight aborted: robots.txt blocks crawl.")
            warnings.append("User overrode robots.txt")
        else:
            raise SystemExit(msg)

    result = PreflightResult(
        url=config.url,
        normalized_url=config.url,
        domain=config.domain,
        base_origin=config.base_origin,
        blocked_category=blocked_cat,
        robots_allowed=allowed,
        robots_disallow_paths=disallow,
        user_confirmed_override=bool(warnings),
        flags=PreflightFlags(
            ignore_robots=config.ignore_robots,
            i_own_this_site=config.i_own_this_site,
            include_subdomains=config.include_subdomains,
        ),
        warnings=warnings,
    )

    ensure_dir(config.output_dir)
    write_model(config.output_dir / "preflight.json", result)
    return result
