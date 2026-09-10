"""
Authentication module. Drives login via Chrome MCP (when available) or
headful Playwright (fallback), then exports a session storage state file
the headless crawler can import.

The integration with Chrome MCP is shimmed through the `_mcp_*` helpers
below. If MCP isn't available, all calls transparently fall back to
launching a Playwright Chromium with `headless=False`.

See references/auth_strategies.md for the full design.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Page

from scripts.config import Config
from scripts.models import AuthProfile
from scripts.utils import ensure_dir, is_purchase_url


log = logging.getLogger(__name__)

DEFAULT_2FA_TIMEOUT = int(os.environ.get("MANUAL_2FA_TIMEOUT_SECONDS", "300"))


async def login(config: Config) -> Path:
    """
    Run the appropriate login strategy for the configured auth profile.

    Returns:
        Path to the persistent user-data directory (NOT a storage_state.json).

    Why persistent user-data dir, not storage_state.json:
      Sites that fingerprint the browser (FingerprintJS / Cloudflare Bot
      Management / etc.) bind the auth cookies to the device fingerprint
      computed at login time. If you transplant the cookies into a fresh
      Chromium context, the fingerprint changes and the server rejects them
      even though the cookies look right.

      The persistent-context approach keeps the same Chromium user data
      directory — same canvas/webgl/audio/font fingerprint, same IndexedDB,
      same localStorage — across the auth → crawl handoff. This is what real
      humans do (they don't change browsers mid-session).

      We still export a storage_state.json into the same .session/ dir so
      downstream code that wants cookies-only can read them, but the crawler
      should use the user-data-dir for everything.
    """
    profile = config.auth_profile
    if profile is None:
        raise ValueError("login() called without auth_profile set")

    # Refuse to log in via a URL that itself matches the purchase blocklist.
    if is_purchase_url(profile.login_url):
        raise RuntimeError(
            f"login_url {profile.login_url!r} matches the purchase URL blocklist. "
            "Aborting login."
        )

    session_dir = ensure_dir(config.output_dir / ".session")
    user_data_dir = ensure_dir(session_dir / "user_data")
    storage_state_path = session_dir / "storage_state.json"

    strategy = profile.effective_strategy
    log.info(f"Auth strategy: {strategy} (profile={profile.safe_repr()})")

    if strategy == "cookie_paste":
        # Cookie paste cannot produce a persistent profile — falls back to
        # the storage_state-only flow.
        await _login_cookie_paste(profile, storage_state_path)
    elif strategy == "manual":
        await _login_manual_persistent(profile, user_data_dir, storage_state_path)
    elif strategy == "automated":
        try:
            await _login_automated_persistent(profile, user_data_dir, storage_state_path)
        except Exception as e:
            log.warning(f"Automated login failed: {e}. Falling back to manual.")
            await _login_manual_persistent(profile, user_data_dir, storage_state_path)
    else:
        log.warning(f"Unknown strategy {strategy!r}; defaulting to manual.")
        await _login_manual_persistent(profile, user_data_dir, storage_state_path)

    # Tighten storage state file permissions (best-effort on Windows).
    try:
        os.chmod(storage_state_path, 0o600)
    except Exception:
        pass

    # Verify session using the SAME persistent profile (same fingerprint).
    test_url = profile.verify_session_url or profile.test_url or _post_login_test_url(profile)
    ok = await verify_session_persistent(
        user_data_dir,
        test_url,
        success_regex=profile.verify_session_success,
    )
    if not ok:
        raise RuntimeError(
            f"Session verification failed for {test_url!r}. "
            "Re-run with strategy=manual in the profile, or set a different "
            "verify_session_url."
        )

    log.info(f"Login successful. Persistent profile: {user_data_dir}")
    log.info(f"Storage state (cookies/origins copy): {storage_state_path}")
    # Return the user-data dir; downstream code now operates on a directory,
    # not a single JSON file.
    return user_data_dir


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

async def _login_automated(profile: AuthProfile, session_path: Path) -> None:
    """Fill the form via selectors, submit, wait, export.

    Safety invariant: the page on which the submit click happens MUST be the
    configured login_url. This is the only place the tool is allowed to
    submit a form on behalf of the user.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        log.info(f"Opening {profile.login_url}")
        await page.goto(profile.login_url, wait_until="domcontentloaded", timeout=30_000)

        log.info("Filling form...")
        await page.locator(profile.username_selector).first.fill(profile.username)
        # NOTE: This is the only point in the codebase that may touch
        # profile.password. Do not log, dump, or otherwise reference it
        # anywhere else.
        await page.locator(profile.password_selector).first.fill(profile.password)

        # Safety assertion: refuse to submit if we somehow ended up on a
        # different URL (e.g. the login page redirected us mid-flow).
        current_url = page.url
        if not _same_login_page(current_url, profile.login_url):
            raise RuntimeError(
                f"Refusing to submit login form: current URL {current_url!r} "
                f"does not match configured login_url {profile.login_url!r}."
            )

        await page.locator(profile.submit_selector).first.click()

        # Handle 2FA
        if profile.two_factor.startswith("totp:"):
            # Out of scope for v1
            raise NotImplementedError(
                "TOTP auto-fill not implemented. Set TWO_FACTOR=manual."
            )
        elif profile.two_factor == "manual":
            await _pause_for_2fa(page, profile)

        # Wait for post-login condition
        await _wait_for_post_login(page, profile)

        # Export storage state
        await ctx.storage_state(path=str(session_path))
        await browser.close()


def _same_login_page(current: str, configured: str) -> bool:
    """Loose equality: ignore trailing slash, query, fragment."""
    def norm(u: str) -> str:
        u = u.split("#", 1)[0].split("?", 1)[0]
        return u.rstrip("/").lower()
    return norm(current) == norm(configured)


async def _login_manual_persistent(
    profile: AuthProfile,
    user_data_dir: Path,
    storage_state_path: Path,
) -> None:
    """Open the login page in a *persistent* headed browser, wait for the
    user to log in by hand, then export a storage_state copy alongside the
    user-data-dir.

    The persistent context preserves the browser fingerprint across the
    auth → crawl handoff, which is required for sites that bind sessions
    to a FingerprintJS / Cloudflare device ID.
    """
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=False,
            # Stable viewport + realistic UA help avoid bot-detection
            # heuristics, although the FingerprintJS bypass comes mostly
            # from re-using the user-data-dir on the crawl side.
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(profile.login_url, wait_until="domcontentloaded", timeout=30_000)

        log.warning(
            "[auth] Manual login mode. The Chromium window is open at the "
            "login page. Log in by hand using:"
        )
        log.warning(f"[auth]   email:    {profile.username}")
        log.warning("[auth]   password: (in .dna-website.env — never echoed here)")
        log.warning(
            "[auth] Once you reach the post-login state I'll detect it "
            "automatically and continue. Do NOT click anything that says "
            "'Buy', 'Upgrade', 'Subscribe' etc."
        )

        await _wait_for_post_login(page, profile)

        # Give the site a moment to set any post-login cookies it deferred.
        await asyncio.sleep(2)

        await ctx.storage_state(path=str(storage_state_path))
        await ctx.close()


async def _login_automated_persistent(
    profile: AuthProfile,
    user_data_dir: Path,
    storage_state_path: Path,
) -> None:
    """Automated form fill in a persistent context (same fingerprint benefits)."""
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=False,
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        log.info(f"Opening {profile.login_url}")
        await page.goto(profile.login_url, wait_until="domcontentloaded", timeout=30_000)

        log.info("Filling form...")
        await page.locator(profile.username_selector).first.fill(profile.username)
        # NOTE: only point in the codebase that touches profile.password.
        await page.locator(profile.password_selector).first.fill(profile.password)

        current_url = page.url
        if not _same_login_page(current_url, profile.login_url):
            raise RuntimeError(
                f"Refusing to submit login form: current URL {current_url!r} "
                f"does not match configured login_url {profile.login_url!r}."
            )

        await page.locator(profile.submit_selector).first.click()

        if profile.two_factor.startswith("totp:"):
            raise NotImplementedError("TOTP auto-fill not implemented; use strategy=manual.")
        elif profile.two_factor == "manual":
            await _pause_for_2fa(page, profile)

        await _wait_for_post_login(page, profile)
        await asyncio.sleep(2)
        await ctx.storage_state(path=str(storage_state_path))
        await ctx.close()


async def verify_session_persistent(
    user_data_dir: Path,
    test_url: str,
    *,
    success_regex: str | None = None,
) -> bool:
    """Verify the session by reopening the SAME persistent context.

    Critical: must use headed mode (headless=False) — sites that fingerprint
    the browser see headless as a distinct device. We need bit-for-bit the
    same fingerprint as login to reuse the auth cookies.
    """
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=False,
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            resp = await page.goto(test_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            log.warning(f"Verify navigation failed: {e}")
            await ctx.close()
            return False

        # Give SPA frameworks time to render the post-auth chrome.
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        await asyncio.sleep(2)

        final_url = page.url
        status = resp.status if resp else 0

        content: str = ""
        try:
            content = await page.content()
        except Exception:
            pass

        await ctx.close()

        if status in (401, 403):
            log.warning(f"Verify got HTTP {status} for {test_url}")
            return False
        if any(kw in final_url for kw in ["/login", "/signin", "/auth/"]):
            log.warning(f"Verify redirected to login: {final_url}")
            return False
        if success_regex:
            try:
                if not re.search(success_regex, content):
                    log.warning(
                        f"Verify content did not match success regex "
                        f"{success_regex!r} (final_url={final_url}, content len={len(content)})"
                    )
                    return False
            except re.error as e:
                log.warning(f"Invalid verify_session_success regex: {e}")
        return True


async def _login_manual(profile: AuthProfile, session_path: Path) -> None:
    """Open the login page in a headed browser, wait for the user to log in
    by hand, auto-detect the post-login state, then export storage state.

    Detection is purely passive — we poll the page URL and DOM, never click
    or fill anything. The user just logs in normally; once the URL matches
    `post_login_url_pattern` (regex) or `post_login_url_contains` (substring)
    or `post_login_selector` is present, we export and close.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(profile.login_url, wait_until="domcontentloaded", timeout=30_000)

        # Banner the user sees in the terminal — never includes the password.
        log.warning(
            "[auth] Manual login mode. The Chromium window is open at the "
            f"login page. Log in by hand using:"
        )
        log.warning(f"[auth]   email:    {profile.username}")
        log.warning(f"[auth]   password: (in .dna-website.env — never echoed here)")
        log.warning(
            "[auth] Once you reach the post-login state I'll detect it "
            "automatically and continue. Do NOT click anything that says "
            "'Buy', 'Upgrade', 'Subscribe' etc."
        )

        # Auto-detect post-login state. _wait_for_post_login deadline defaults
        # to DEFAULT_2FA_TIMEOUT seconds, which is plenty for a manual login.
        await _wait_for_post_login(page, profile)

        await ctx.storage_state(path=str(session_path))
        await browser.close()


async def _login_cookie_paste(profile: AuthProfile, session_path: Path) -> None:
    """
    Last resort: user prepares a cookies file, points us at it via the
    DNA_COOKIES_FILE env var. Format expected inside the file:
        Cookie: name=value; name=value; name=value
    or just `name=value; name=value`.
    """
    cookies_file = os.environ.get("DNA_COOKIES_FILE")
    if not cookies_file:
        raise RuntimeError(
            "Cookie-paste mode requires DNA_COOKIES_FILE env var pointing at "
            "a file containing the cookie string. Aborting."
        )
    raw = Path(cookies_file).read_text().strip()
    cookies = _parse_cookie_string(raw, profile.cookie_domain or "")
    storage = {"cookies": cookies, "origins": []}
    ensure_dir(session_path.parent)
    session_path.write_text(json.dumps(storage, indent=2))


def _parse_cookie_string(raw: str, domain: str) -> list[dict[str, Any]]:
    """Parse 'name=value; name=value' into Playwright cookie dicts."""
    raw = raw.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[len("cookie:"):].strip()
    out = []
    for pair in raw.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        out.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": domain,
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        })
    return out


# ---------------------------------------------------------------------------
# Post-login helpers
# ---------------------------------------------------------------------------

async def _wait_for_post_login(page: Page, profile: AuthProfile) -> None:
    """Wait for the URL-pattern (regex), URL-contains, or selector condition
    that signals login success. Deadline is long because manual logins can
    take a minute or two."""
    deadline = asyncio.get_event_loop().time() + DEFAULT_2FA_TIMEOUT

    pattern: re.Pattern[str] | None = None
    if profile.post_login_url_pattern:
        try:
            pattern = re.compile(profile.post_login_url_pattern)
        except re.error as e:
            log.warning(f"Invalid post_login_url_pattern: {e}")

    while asyncio.get_event_loop().time() < deadline:
        url = page.url
        if pattern and pattern.search(url):
            return
        if (not pattern
            and profile.post_login_url_contains
            and profile.post_login_url_contains in url):
            return
        if profile.post_login_selector:
            try:
                if await page.locator(profile.post_login_selector).count() > 0:
                    return
            except Exception:
                pass
        await asyncio.sleep(0.5)

    raise TimeoutError(
        f"Did not reach post-login state. URL is {page.url!r}; "
        f"expected pattern {profile.post_login_url_pattern!r} or "
        f"substring {profile.post_login_url_contains!r}"
    )


async def _pause_for_2fa(page: Page, profile: AuthProfile) -> None:
    """Pause for the user to complete 2FA in the open browser window.

    Passive: we don't read stdin. We just wait for the post-login condition
    to become true via _wait_for_post_login (which is called next anyway).
    The 2FA delay is folded into the post-login wait.
    """
    log.warning(
        f"[auth] Complete 2FA in the open Chromium window. I'll auto-detect "
        f"the post-login state (up to {DEFAULT_2FA_TIMEOUT}s)."
    )
    # Nothing to do here — _wait_for_post_login below handles the polling.


def _post_login_test_url(profile: AuthProfile) -> str:
    """If no explicit test URL, derive from the login URL + post-login hint."""
    if profile.test_url:
        return profile.test_url
    base = profile.login_url.split("?")[0].rsplit("/", 1)[0]
    if profile.post_login_url_contains and profile.post_login_url_contains.startswith("/"):
        return base + profile.post_login_url_contains
    return profile.login_url


async def verify_session(
    storage_state_path: Path,
    test_url: str,
    *,
    success_regex: str | None = None,
) -> bool:
    """
    Open test_url in a fresh headless context using the exported session.
    Return True if not redirected to login, HTTP < 400, and (if a
    success_regex is supplied) the rendered page content matches it.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state=str(storage_state_path))
        page = await ctx.new_page()
        try:
            resp = await page.goto(test_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            log.warning(f"Verify navigation failed: {e}")
            await browser.close()
            return False

        final_url = page.url
        status = resp.status if resp else 0

        content: str = ""
        try:
            content = await page.content()
        except Exception:
            pass

        await browser.close()

        if status in (401, 403):
            log.warning(f"Verify got HTTP {status} for {test_url}")
            return False
        if any(kw in final_url for kw in ["/login", "/signin", "/auth/"]):
            log.warning(f"Verify redirected to login: {final_url}")
            return False
        if success_regex:
            try:
                if not re.search(success_regex, content):
                    log.warning(
                        f"Verify content did not match success regex "
                        f"{success_regex!r} (final_url={final_url})"
                    )
                    return False
            except re.error as e:
                log.warning(f"Invalid verify_session_success regex: {e}")
                # Don't fail solely on a bad regex.
        return True


# ---------------------------------------------------------------------------
# Chrome MCP integration (shim — implement when MCP API is available)
# ---------------------------------------------------------------------------
#
# The intended pattern when running inside a Claude session with Chrome MCP:
#
#   1. Use MCP `navigate` tool to open the login URL in the existing Chrome
#   2. Use MCP `find` or `read_page` to locate form fields by selectors
#   3. Use MCP `form_input` or `computer` to fill them
#   4. Pause for 2FA via Claude prompting the user
#   5. Use MCP `javascript_tool` to dump `document.cookie` + localStorage
#   6. Reconstruct Playwright storage_state from that data
#
# Implementation note: the MCP shim should be a separate module
# (scripts/mcp_shim.py) that the auth strategies CAN call but don't HAVE to.
# Always preserve the Playwright-direct fallback. This keeps the tool usable
# even outside of a Claude session.
#
# ---------------------------------------------------------------------------
