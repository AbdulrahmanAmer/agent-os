"""
Configuration loading from CLI args + .dna-website.env.

The Config dataclass is passed to every pipeline stage. Stages should never
reach back to argparse or environ — everything they need is in Config.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from scripts.models import AuthProfile
from scripts.utils import domain_of, normalize_url, origin_of


@dataclass
class Config:
    # Target
    url: str
    base_origin: str
    domain: str

    # Output
    output_dir: Path

    # Crawl options
    depth: int = 4
    max_pages: int = 200
    max_asset_size_mb: int = 50
    include_subdomains: bool = False
    skip_assets: bool = False
    mobile_also: bool = False
    rate_limit: float = 2.0          # requests per second
    concurrency: int = 3

    # Auth
    auth_profile: AuthProfile | None = None

    # Overrides
    ignore_robots: bool = False
    i_own_this_site: bool = False
    resume: bool = False
    verbose: bool = False

    # Internal
    started_at: datetime = field(default_factory=datetime.utcnow)
    headed: bool = False             # forced True if DNA_HEADED env var set


def build_config(
    url: str,
    *,
    auth: str | None = None,
    depth: int = 4,
    max_pages: int = 200,
    max_asset_size_mb: int = 50,
    include_subdomains: bool = False,
    skip_assets: bool = False,
    mobile_also: bool = False,
    output: str | None = None,
    resume: bool = False,
    ignore_robots: bool = False,
    i_own_this_site: bool = False,
    rate_limit: float = 2.0,
    concurrency: int = 3,
    verbose: bool = False,
    env_file: str = ".dna-website.env",
) -> Config:
    """
    Build a validated Config from CLI inputs.

    Raises:
        ValueError if url is malformed or auth profile is missing.
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"URL must include scheme (http/https): {url!r}")

    normalized = normalize_url(url)
    base_origin = origin_of(normalized)
    domain = domain_of(normalized)

    # Output directory: ./dna-output/<domain>-<YYYYMMDD-HHMMSS>
    if output:
        output_dir = Path(output)
    else:
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        output_dir = Path("dna-output") / f"{domain}-{stamp}"

    # Auth
    auth_profile = None
    if auth:
        auth_profile = load_auth_profile(auth, env_file)

    return Config(
        url=normalized,
        base_origin=base_origin,
        domain=domain,
        output_dir=output_dir,
        depth=depth,
        max_pages=max_pages,
        max_asset_size_mb=max_asset_size_mb,
        include_subdomains=include_subdomains,
        skip_assets=skip_assets,
        mobile_also=mobile_also,
        rate_limit=rate_limit,
        concurrency=concurrency,
        auth_profile=auth_profile,
        ignore_robots=ignore_robots,
        i_own_this_site=i_own_this_site,
        resume=resume,
        verbose=verbose,
        headed=bool(os.environ.get("DNA_HEADED")),
    )


def load_auth_profile(name: str, env_file: str = ".dna-website.env") -> AuthProfile:
    """
    Load a named profile from an INI-style env file.

    Accepts two key schemas:
      1. Lowercase, strategy-based (preferred):
           url, strategy, login_url, email, password,
           post_login_url_pattern, verify_session_url, verify_session_success,
           email_selector, password_selector, submit_selector
      2. Legacy UPPERCASE:
           LOGIN_URL, USERNAME, PASSWORD, POST_LOGIN_URL_CONTAINS,
           MANUAL_LOGIN, MANUAL_COOKIE_PASTE, etc.

    Either schema works; the lowercase one is what the prompt + new
    .dna-website.env.example use.

    Raises:
        FileNotFoundError if env file is missing.
        KeyError if profile is not in the file.
        ValueError if required fields are missing.
    """
    path = Path(env_file)
    if not path.exists():
        raise FileNotFoundError(
            f"{env_file} not found. Copy .dna-website.env.example to "
            f"{env_file} and add your profile."
        )

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path)

    if name not in parser:
        raise KeyError(
            f"Auth profile {name!r} not found in {env_file}. "
            f"Available: {list(parser.sections())}"
        )

    section = parser[name]

    def g(*keys: str, default: str | None = None) -> str | None:
        """Return the first key present in the section (case-insensitive)."""
        # configparser already case-folds keys (defaults to lowercase). Be
        # defensive: try the supplied casing first, then upper, then lower.
        for k in keys:
            for variant in (k, k.upper(), k.lower()):
                if variant in section and section.get(variant):
                    return section.get(variant)
        return default

    login_url = g("login_url", "LOGIN_URL")
    username = g("email", "username", "EMAIL", "USERNAME")
    password = g("password", "PASSWORD")

    missing = [
        label for label, val in (
            ("login_url", login_url),
            ("email/username", username),
            ("password", password),
        ) if not val
    ]
    if missing:
        raise ValueError(
            f"Profile {name!r} is missing required keys: {missing}. "
            f"Expected (lowercase) login_url, email, password. "
            f"See .dna-website.env.example."
        )

    return AuthProfile(
        name=name,
        url=g("url", "URL"),
        login_url=login_url,
        username=username,
        password=password,
        strategy=(g("strategy", "STRATEGY") or "manual").lower(),
        username_selector=g(
            "email_selector", "username_selector",
            "EMAIL_SELECTOR", "USERNAME_SELECTOR",
            default='input[type="email"], input[name="email"]',
        ),
        password_selector=g(
            "password_selector", "PASSWORD_SELECTOR",
            default='input[type="password"], input[name="password"]',
        ),
        submit_selector=g(
            "submit_selector", "SUBMIT_SELECTOR",
            default='button[type="submit"]',
        ),
        post_login_url_contains=g(
            "post_login_url_contains", "POST_LOGIN_URL_CONTAINS",
            default="/",
        ),
        post_login_url_pattern=g("post_login_url_pattern", "POST_LOGIN_URL_PATTERN"),
        post_login_selector=g("post_login_selector", "POST_LOGIN_SELECTOR"),
        verify_session_url=g("verify_session_url", "VERIFY_SESSION_URL", "test_url", "TEST_URL"),
        verify_session_success=g("verify_session_success", "VERIFY_SESSION_SUCCESS"),
        two_factor=g("two_factor", "TWO_FACTOR", default="manual"),
        manual_login=(g("manual_login", "MANUAL_LOGIN", default="false") or "false").lower() == "true",
        manual_cookie_paste=(g("manual_cookie_paste", "MANUAL_COOKIE_PASTE", default="false") or "false").lower() == "true",
        cookie_domain=g("cookie_domain", "COOKIE_DOMAIN"),
        test_url=g("test_url", "TEST_URL", "verify_session_url", "VERIFY_SESSION_URL"),
    )
