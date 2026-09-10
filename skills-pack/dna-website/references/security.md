# Security model

> Every design decision in this tool that touches authentication, credentials, or output should be checked against this doc.

---

## Threat model

This tool runs on the user's machine, with the user's credentials, against websites the user claims they have permission to inspect. The threats we defend against:

1. **Credential leakage into output artifacts.** A user crawls an authenticated dashboard, shares the output folder with a colleague to discuss the design — and the colleague now has the user's auth tokens. This is the #1 risk.
2. **Crawling sites the user shouldn't.** A user (intentionally or not) points the tool at a banking site, a government site, or a site with an explicit no-bot policy. We can't stop them outright, but we add friction.
3. **Crawling-induced denial of service.** A poorly tuned crawler hits a small site with 50 concurrent requests and gets the user IP-banned (or worse, takes the site down).
4. **Malicious site content executing in our context.** A crawled page contains JS that tries to exfiltrate cookies via a redirect, or that mines crypto in our headless browser. Lower risk because we don't persist or share the browser state with the user's main browser, but worth defending.
5. **Prompt injection via page content.** Captured HTML eventually ends up in a context where another LLM might read it — and an attacker could embed instructions in the page hoping a downstream agent acts on them. We mitigate by treating all captured content as untrusted data.

---

## Defenses

### 1. Credential leakage into output artifacts

**Where credentials enter the system:**
- Auth profile file (`.dna-website.env`)
- Interactive 2FA prompts
- Cookie paste flow
- The browser's storage state after login

**Where they could leak:**
- Network logs (Cookie/Authorization headers)
- HTML pages (form values, hidden inputs)
- JSON-LD or page metadata (rarely)
- Error messages and stack traces
- Log files
- The session export itself

**Sanitization layers** (in `scripts/utils.py`):
1. **Header allowlist**: `SENSITIVE_HEADERS` set covers Authorization, Cookie, Set-Cookie, X-API-Key, X-Auth-Token, X-CSRF-Token, X-Session-ID. All redacted to `***REDACTED***`.
2. **JSON field allowlist**: `SENSITIVE_JSON_FIELDS` covers password, token, secret, api_key, access_token, refresh_token, jwt, bearer, session, csrf.
3. **Token-shape detection**: `TOKEN_VALUE_PATTERNS` regex catches JWT (3 base64 segments), Stripe keys (`sk_live_*`, `pk_test_*`), GitHub PATs (`ghp_*`), Slack tokens (`xox*-*`), and any base64-looking string ≥ 20 chars in a sensitive context.
4. **URL parameter cleaning**: `SENSITIVE_QUERY_KEYS` covers token, api_key, key, secret, password, auth, sig, signature, jwt, bearer. Values replaced with `REDACTED` in query strings.
5. **Form value scrubbing**: when capturing form fields, `<input type="password">` values are always stripped. Other input values stripped unless explicitly opted in.

**Storage state isolation:**
- `storage_state.json` lives at `.session/<profile>/storage_state.json`, mode 0600
- `.session/` is in the default `.gitignore`
- It is the ONE artifact that legitimately contains auth state. Nothing else may.
- Pre-commit hook (`no-session-files`) blocks accidental commits.

**Output directory audit:**
- Run this after every crawl: `make audit-output DIR=<output-dir>` (defined in Makefile)
- Greps every file for credential-shaped strings and reports any matches
- CI runs the same audit against test outputs

### 2. Stopping users from crawling sites they shouldn't

**Hard-blocked categories** (`BLOCKED_DOMAINS` in `scripts/preflight.py`):
- Banking: chase.com, bankofamerica.com, wellsfargo.com, etc.
- Government: *.gov, *.gov.uk, *.gc.ca, *.gov.au
- Healthcare: *.healthcare.gov, kaiserpermanente.org, *.nih.gov
- Dating: tinder.com, bumble.com, hinge.co, match.com

These produce an immediate refusal unless the user passes `--i-own-this-site` AND types the domain back when prompted. The list is conservative; users with legitimate needs (e.g., bank UX team studying their own site) can override.

**robots.txt:**
- Always fetched in preflight.
- Disallow rules are respected by default. The crawler skips any URL matching a Disallow path.
- `--ignore-robots` overrides, with an interactive prompt and a 5-second timer before continuing.

**Crawl-Delay directives:**
- If robots.txt specifies `Crawl-Delay`, the crawler clamps `--rate-limit` to match (cannot be more aggressive than the site asks).

### 3. Crawling-induced DoS

**Defaults are conservative:**
- 2 requests/second globally
- 3 parallel browser contexts (effective concurrency 3, but shared rate limit)
- 200 max pages
- Depth 4

**Rate limiter implementation:**
- Token bucket shared across all contexts (`crawl.py`)
- Asset downloader has its own bucket (`download_assets.py`)
- Both buckets honor the `Retry-After` header when a 429 comes back

**Backoff on errors:**
- Exponential backoff with jitter on any 5xx or 429
- 3 retries max; after that the page is marked failed and the run continues

### 4. Malicious site content executing in browser context

**Isolation guarantees:**
- Every crawled site runs in a fresh Playwright browser context with no persistent profile
- We never share state across runs unless `--resume` is set, and even then only the cookies the user authorized
- No browser extensions are loaded
- The user's main browser cookies/passwords/etc. are never accessed

**JS execution scope:**
- We DO execute the site's JS (it's how SPAs render). This is a deliberate trade-off.
- We DO NOT navigate to off-origin frames or follow redirects to other domains during the asset phase (the asset phase is plain HTTP).
- Files downloaded as assets are written to disk and never executed.

### 5. Prompt injection via page content

The output files contain captured HTML, which may contain attacker-controlled text claiming to be instructions. When downstream tools (a rebuild agent, a documentation summarizer) read these files:

**Defenses applied at output time:**
- Captured HTML is stored verbatim in `raw/pages/<slug>/source.html` and `rendered.html`. These are clearly labeled as untrusted data.
- The content inventory (`analysis/content-inventory.json`) preserves text exactly as captured. We don't transform or "clean" it.
- The REPORT.md generated by `report.py` truncates long content snippets and does not pass them through unfiltered. Where it must include captured text, it labels it as "from {url}".
- The inspector wraps pages in an iframe-like sandbox (`templates/inspector_page.html.j2`) so any active content is visually contained.

**Defenses recommended for downstream consumers:**
- Treat anything under `raw/` and any string field in `analysis/content-inventory.json` as untrusted.
- Apply standard prompt-injection defenses (instruction isolation, role-restricted prompts) when feeding these to an LLM.
- The `swap-map.json` is safe (machine-generated) but the keys derived from page content may contain injection attempts.

---

## Security review checklist (for every PR)

- [ ] No new credential storage location introduced (other than `.session/`)
- [ ] If a new HTTP request is added, it goes through the rate limiter
- [ ] If a new JSON write is added, the data passes through `sanitize_json` first if it could contain user data
- [ ] If a new header is logged, it's checked against `SENSITIVE_HEADERS`
- [ ] If a new error message is added, it does not include the raw URL params or request body
- [ ] If a new dependency is added, it's been audited for known CVEs (`pip-audit` for Python, `npm audit` for Node)

---

## Incident response

If you discover that this tool has leaked credentials in an output directory:

1. **Don't share the output.** Stop any pending PR or upload immediately.
2. **Identify the leakage path.** Which file? Which sanitization layer should have caught it?
3. **Rotate the affected credentials.** Treat them as compromised.
4. **Add a regression test.** A new entry in `tests/test_sanitization_fuzz.py` (M1).
5. **Fix the sanitizer.** Make the test pass.
6. **Patch every prior run.** If users have shared output directories already, document the leak in `docs/CHANGELOG.md` with the affected version and the kind of credential at risk.

---

## What this tool will never do, regardless of user request

- Submit forms with user credentials to login pages on the user's behalf (the user does the login themselves; we only capture the resulting session state)
- Bypass CAPTCHA or anti-bot systems
- Crawl a site if its `X-Robots-Tag: noindex, nofollow` header is present (treated as a soft block; prompts for override)
- Store the user's password in plaintext anywhere — passwords entered during interactive login go straight to the browser, never to Python state
- Upload any captured data to a remote service
- Send analytics or telemetry about runs
