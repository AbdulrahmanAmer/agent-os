# Troubleshooting

Common failure modes and how the tool handles them. Each entry: symptom → cause → mitigation already in code → manual override if you need it.

## Auth failures

### "Verify session failed" after successful login
- **Cause:** Login succeeded in headful Chrome but the storage state export missed an HttpOnly cookie, OR the test URL redirects everyone (logged-in or not) to a login page.
- **Built-in mitigation:** `scripts/auth.py:verify_session` retries once with a 2s delay; tries the post-login URL as the test URL if no test URL is set.
- **Manual override:** Set a different `POST_LOGIN_URL_CONTAINS` and a known-authenticated `TEST_URL` in the profile. Or switch to `MANUAL_COOKIE_PASTE=true`.

### "Selector not found" during automated login
- **Cause:** Site's form selectors changed, are dynamically generated, or live inside a shadow DOM / iframe.
- **Built-in mitigation:** Falls back to `MANUAL_LOGIN=true` after one retry.
- **Manual override:** Inspect the live form in DevTools, update `USERNAME_SELECTOR` / `PASSWORD_SELECTOR` / `SUBMIT_SELECTOR`. For shadow DOM, you may need to use Playwright's `>>>` piercing selector syntax.

### 2FA timeout
- **Cause:** User didn't complete 2FA within the wait window (default 5 min).
- **Built-in mitigation:** Prompt waits indefinitely after the initial timeout, displaying the elapsed time.
- **Manual override:** Bump `MANUAL_2FA_TIMEOUT_SECONDS` env var (default 300).

## Crawler failures

### "Cloudflare challenge" page on every request
- **Cause:** Anti-bot service detected the headless Chromium.
- **Built-in mitigation:** Crawler launches in headful mode by default when `--auth` is set. Uses a real Chrome user agent. Includes a `--stealth` flag that injects fingerprint shims (overrides `navigator.webdriver`, plugin list, languages, etc).
- **Manual override:** Try `--use-system-chrome` to use the user's installed Chrome rather than Playwright's bundled Chromium. If still blocked, the site likely requires a paid solution like Bright Data or a residential proxy — out of scope for this tool. Crawl with `--manual-pages` listing only the pages you can verify yourself.

### 429 Too Many Requests
- **Cause:** Rate limit exceeded.
- **Built-in mitigation:** Per-request retry with exponential backoff (`tenacity`). After 3 retries, page is marked failed and crawl continues. Global rate limit drops to half its current value after the first 429.
- **Manual override:** `--rate-limit 0.5` (one request every 2 seconds) and `--concurrency 1`.

### Infinite scroll content missed
- **Cause:** Page lazily loads content as you scroll. The crawler stops at network idle, which happens before the user-triggered loads.
- **Built-in mitigation:** `scripts/crawl.py:scroll_to_load_all` is invoked when `<page contains "infinite-scroll" or lazy-load patterns>`. It scrolls to the bottom, waits 2s, repeats until the document height stops growing (or 30s max).
- **Manual override:** `--always-scroll` enables this for every page.

### SPA routes not discovered
- **Cause:** Client-side routing via `history.pushState` is invisible to plain HTML crawling.
- **Built-in mitigation:** The crawler's injected script (`browser_scripts/extract_spa_routes.js`) hooks `pushState` and `replaceState`, and also scans for framework artifacts (Next.js `_next/data`, Nuxt `__NUXT__.routes`, generic `data-route` attributes, etc).
- **Manual override:** Provide a `--routes-file <path>` with one URL per line; the discover stage will merge them with auto-discovered routes.

### `wait_until="networkidle"` hangs
- **Cause:** Page never reaches network idle (long-polling, websockets, ad networks).
- **Built-in mitigation:** Falls back to `domcontentloaded` + 3s settle after 30s timeout.
- **Manual override:** `--wait-strategy domcontentloaded` skips networkidle entirely.

## Asset download failures

### Asset URLs are 404 / CORS-blocked
- **Cause:** URL was resolved from a CSS file relative to the wrong base, or the asset is gated behind auth that the asset downloader's plain `aiohttp` doesn't replay.
- **Built-in mitigation:** Asset downloader runs in two phases. Phase 1: plain HTTP. Phase 2: any failures retry via Playwright with the imported session state.
- **Manual override:** `--all-assets-via-browser` forces Phase 2 for everything (slower but more reliable for hostile sites).

### Asset download blows past time budget
- **Cause:** Site has thousands of tiny SVGs or megabytes of images per page.
- **Built-in mitigation:** Per-asset timeout (30s default), max asset size (50 MB default).
- **Manual override:** `--max-asset-size 10` to skip larger files. `--skip-assets` to skip the stage entirely (useful for "I just want the design tokens" runs).

### Web fonts not downloaded
- **Cause:** Fonts referenced via `@font-face { src: url(fonts.gstatic.com/...) }` aren't in the page DOM, only in stylesheets.
- **Built-in mitigation:** The asset downloader parses every captured stylesheet's `@font-face` rules and includes the `src` URLs.
- **Manual override:** If Google Fonts URLs still escape, add them to a `--extra-asset-urls` file.

## Analysis failures

### Color palette has 50 brand colors
- **Cause:** K-means k was set too high, or the site genuinely uses tons of colors.
- **Built-in mitigation:** k is chosen automatically from `[6, 8, 12, 16, 20]` via silhouette score.
- **Manual override:** Edit `K_CANDIDATES` in `scripts/analyze_dna.py`. If the site really uses 50 distinct brand colors, that's the answer — surface it in `REPORT.md`.

### "No brand color identified"
- **Cause:** Site uses only neutrals (gray, black, white) — common for news, minimalist portfolios.
- **Built-in mitigation:** Warning written to `REPORT.md`. Neutrals + accents still extracted.
- **Manual override:** None needed; this is the correct output for the input.

### Typography scale is `null`
- **Cause:** Font sizes don't follow a consistent ratio.
- **Built-in mitigation:** Raw sizes still written; `scale_ratio: null` flagged in output.
- **Manual override:** None needed; report what's there.

### Component patterns is empty
- **Cause:** Site is unusually small (< 5 pages) or every page has unique structure.
- **Built-in mitigation:** Threshold can be lowered via `COMPONENT_MIN_OCCURRENCE`.
- **Manual override:** `--component-threshold 2` (also catches pairs).

## Local inspector failures

### Inspector shows broken images
- **Cause:** HTML asset paths weren't rewritten to local files.
- **Built-in mitigation:** `scripts/serve.py` runs `rewrite_paths()` on every page when prepping inspector output. Errors are logged.
- **Manual override:** Check `inspector/pages/<slug>.html` for unrewritten URLs. The fix is usually in the path-rewrite regex in `scripts/utils.py:rewrite_html_asset_paths`.

### Inspector shows raw HTML for some pages
- **Cause:** Page capture failed silently; the rendered.html is malformed.
- **Built-in mitigation:** Failed captures are excluded from the inspector index.
- **Manual override:** Check `captures.json` for the page; look at its `error_message`; re-run that page with `--routes-file` containing just that URL.

### Port 7777 already in use
- **Cause:** Previous inspector still running.
- **Built-in mitigation:** None — the user picks the next port.
- **Manual override:** `node node_helpers/inspector_server.mjs <dir> --port 7778`.

## Performance issues

### Crawl takes hours
- **Cause:** Probably `wait_until=networkidle` waits + many pages + concurrency 1.
- **Investigation:** Look at `run.log` for per-page durations. If most pages take >10s, it's wait strategy; if they're fast but the total is huge, it's page count.
- **Fix:** `--max-pages 50` to bound it. `--concurrency 3` if you're not getting rate-limited. `--wait-strategy domcontentloaded` for sites with eternal long-polling.

### Output directory is gigabytes
- **Cause:** Big screenshots, big media files.
- **Investigation:** `du -sh dna-output/<dir>/raw/*` to find the offender.
- **Fix:** `--max-asset-size 5`. `--skip-screenshots-mobile`. Consider whether you actually need video files for design reference.

## When all else fails

1. Re-run with `--verbose` and check `run.log`.
2. Re-run a single page via `python -m scripts.crawl --url <url> --debug`.
3. Open Playwright in headed mode by setting `DNA_HEADED=1` env var. Watch what the crawler sees.
4. Save a known-good run as a regression baseline (`tests/baselines/<site>.json`) and diff future runs against it.
