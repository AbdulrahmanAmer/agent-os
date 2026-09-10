# Auth Strategies

This document covers how the tool handles authentication. The core problem: bots are bad at login (CAPTCHAs, 2FA, custom JS forms, bot detection), but humans are good at it. The solution: let the human handle login via Chrome MCP, then export the resulting session for fast bot crawling.

## The fundamental flow

```
┌────────────────────────────────────────────────────────────────┐
│                      Auth Pipeline                              │
└────────────────────────────────────────────────────────────────┘

1. Load profile from .dna-website.env
2. Launch Chrome MCP, navigate to LOGIN_URL
3. Try selector-based fill (USERNAME_SELECTOR, PASSWORD_SELECTOR)
4. Submit form (SUBMIT_SELECTOR)
5. If TWO_FACTOR != "none":
      Pause and prompt user to complete 2FA in the open window
6. Wait for POST_LOGIN_URL_CONTAINS or POST_LOGIN_SELECTOR
7. Export storage_state (cookies + localStorage + sessionStorage)
8. Verify session by opening a known authenticated URL in a
   fresh headless Playwright context with imported state
9. Hand storage_state.json to the crawler

Failure at any step → fall back to MANUAL_LOGIN=true
```

## Strategy 1: Fully automated (best case)

Works for sites with:
- Standard form-based login
- No CAPTCHA
- No 2FA, or TOTP with secret in the env file
- Stable selectors

Profile:
```ini
[acme]
LOGIN_URL=https://app.acme.com/login
USERNAME=you@example.com
PASSWORD=...
USERNAME_SELECTOR=input[name="email"]
PASSWORD_SELECTOR=input[name="password"]
SUBMIT_SELECTOR=button[type="submit"]
POST_LOGIN_URL_CONTAINS=/dashboard
TWO_FACTOR=none
```

Implementation: see `scripts/auth.py:_attempt_automated_login`.

## Strategy 2: Manual with selectors (most common)

Same as strategy 1, but `TWO_FACTOR=manual`. The script fills the form and submits, then pauses:

```
[auth] Form submitted. Complete 2FA in the open browser window.
[auth] Press Enter here when you've reached the post-login state...
```

User finishes 2FA, hits Enter, script verifies the post-login condition and exports the session.

This is the default recommendation — works for ~90% of sites.

## Strategy 3: Fully manual (fallback)

`MANUAL_LOGIN=true` in the profile. The script:
1. Opens Chrome MCP at `LOGIN_URL`
2. Prints: `[auth] Log in by hand. Press Enter when done.`
3. Waits for Enter
4. Verifies post-login condition
5. Exports session

Use this when:
- Selectors are unstable / heavily-randomized
- The login is SSO-mediated (Google, Microsoft, Okta)
- The site uses a passwordless / magic-link flow
- CAPTCHA is in the way

## Strategy 4: TOTP automation (advanced)

For sites where you control the 2FA secret and want unattended runs:

```ini
TWO_FACTOR=totp:JBSWY3DPEHPK3PXP
```

The script uses Python's `pyotp` (add to deps if you need this) to generate the current code and types it into a configurable `TOTP_SELECTOR`. Not implemented in the v1 — explicitly out of scope unless asked.

## Strategy 5: Cookie paste (escape hatch)

Sometimes login is just too hostile to automate. The escape hatch: let the user log in in their normal browser, paste the session cookie, and use that.

```ini
[hostile-site]
MANUAL_COOKIE_PASTE=true
LOGIN_URL=https://hostile.com/login  # for reference only
POST_LOGIN_URL_CONTAINS=/app
COOKIE_DOMAIN=.hostile.com
```

The script prompts:
```
[auth] Log in to https://hostile.com in your regular browser.
[auth] Open DevTools → Application → Cookies → copy all cookies for .hostile.com
[auth] Paste them here as Cookie: name=value; name=value
[auth] >
```

The script parses, constructs a Playwright `storage_state.json`, and verifies. This is the nuclear option when nothing else works.

## Session verification (critical step)

After any successful login flow, the script **must** verify the session works in a fresh headless context. Why: the storage state export sometimes misses session-bound cookies (HttpOnly + Secure + SameSite=Strict), and an unverified session leads to silent failures in the crawler that look like 401s on every page.

Verification:
```python
async def verify_session(storage_state_path: Path, test_url: str) -> bool:
    """
    Open test_url in a fresh headless context with the exported storage state.
    Return True if the page does not redirect to a login URL and does not show
    a 401/403 status. False otherwise.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state=str(storage_state_path))
        page = await ctx.new_page()
        resp = await page.goto(test_url, wait_until="domcontentloaded", timeout=30000)
        final_url = page.url
        await browser.close()
        if resp.status in (401, 403):
            return False
        if any(kw in final_url for kw in ["/login", "/signin", "/auth"]):
            return False
        return True
```

If verification fails: do not proceed to the crawler. Print actionable diagnostics:
- The final URL after navigation
- The HTTP status of the test request
- Suggest re-running with `MANUAL_LOGIN=true`

## Fallback ladder

When auth fails, walk this ladder in order. Each step is more invasive than the last.

1. **Retry once.** Login flows have flaky timeouts.
2. **Manual completion.** Switch from automated to `MANUAL_LOGIN=true`.
3. **Different test URL.** Maybe the URL used for verification redirects everyone. Try a different known-authenticated URL.
4. **Cookie paste.** Set `MANUAL_COOKIE_PASTE=true`.
5. **Abort.** Tell the user we can't get past auth and ask them to share a different access method or accept a public-only crawl.

## Storage state schema

The `storage_state.json` file follows Playwright's native format:

```json
{
  "cookies": [
    {
      "name": "session_id",
      "value": "abc123...",
      "domain": ".example.com",
      "path": "/",
      "expires": 1735689600,
      "httpOnly": true,
      "secure": true,
      "sameSite": "Lax"
    }
  ],
  "origins": [
    {
      "origin": "https://example.com",
      "localStorage": [
        { "name": "auth_token", "value": "..." }
      ]
    }
  ]
}
```

Generate this with `await context.storage_state(path=...)`. Import with `new_context(storage_state=path)`.

## Chrome MCP integration specifics

When this tool is invoked from inside Claude with Chrome MCP available, the auth flow uses the MCP browser instead of launching its own Playwright Chromium. The integration shape:

```python
# Pseudocode — actual MCP tool names depend on the Chrome MCP version
async def login_via_chrome_mcp(profile: AuthProfile) -> dict:
    # 1. Open the login URL via Chrome MCP
    await mcp_tool("navigate", url=profile.login_url)

    # 2. Use MCP's read_page to get the form structure
    page_data = await mcp_tool("read_page")

    # 3. Use form_input or computer tool to fill the form
    await mcp_tool("form_input",
                   element_id=find_id(page_data, profile.username_selector),
                   value=profile.username)
    # ... etc

    # 4. Submit
    # 5. If 2FA, prompt user (Claude pauses, user completes in MCP browser)
    # 6. Export cookies via Chrome MCP cookie tool, or:
    #    - Run javascript_tool to dump document.cookie + localStorage
    #    - Reconstruct Playwright storage state from that
    return reconstructed_storage_state
```

The exact MCP tool names will need adjustment based on the Chrome MCP build available. Treat `scripts/auth.py:login_via_chrome_mcp` as the integration shim — keep the rest of the codebase agnostic to whether auth came from Playwright-launched Chrome or Chrome MCP.

**If Chrome MCP isn't available**, the script falls back to launching its own headful Playwright Chromium. This works fine for most cases; the only loss is that the user has to look at a second browser window.

## What never gets written to disk

These rules are enforced in `scripts/utils.py:sanitize_*` and tested in `tests/test_smoke.py`:

- Passwords. Ever. They live in `.dna-website.env`, are loaded into memory, used once, and never logged or serialized.
- `Authorization: Bearer ...` headers in network logs.
- Set-Cookie response headers.
- Query string `?token=...`, `?api_key=...`, `?key=...` in network logs.
- JSON body fields named `password`, `secret`, `token`, `access_token`, `refresh_token`, `api_key`, etc.
- JWT-looking strings (start with `eyJ`).
- Stripe-looking keys (`sk_live_`, `pk_live_`, `rk_live_`).

The session file (`storage_state.json`) does contain auth cookies — that's the whole point. It's written to `output/.session/` with mode `0600` and the output directory is in `.gitignore`.

## Testing the auth module

Write tests against a controlled login. Recommended test target: GitHub login with a throwaway account that has nothing in it. Procedure:

1. Run `python -m scripts.auth --profile github-test`.
2. Verify `output/.session/storage_state.json` is produced.
3. Verify session works by running `python -m scripts.auth --verify-only --profile github-test --test-url https://github.com/settings/profile`.
4. Verify nothing sensitive leaked into `output/run.log`.

Do not commit any working `.dna-website.env` to the test fixtures — only commit the example file.
