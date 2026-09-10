# Glossary

> Terms used throughout the docs and code. If you're confused by a term, it should be here.

---

## A

**A11y tree** — Accessibility tree. The semantic structure of a page as exposed to assistive tech. Captured per page in `raw/pages/<slug>/a11y-tree.json` via Playwright's `page.accessibility.snapshot()`.

**Asset manifest** — `raw/assets/manifest.json`. Lists every asset URL discovered, its content hash, its local path, its source pages, its download status. The authoritative index for the asset pipeline.

**Authentication profile** — A named entry in `.dna-website.env` describing how to log into a specific target. Includes URL, strategy, selectors, and verification rules. **Never** includes plaintext passwords for production targets.

---

## B

**Blocked category** — A domain category the tool refuses to process by default. Includes banking, government, healthcare, and dating. See `scripts/preflight.py:BLOCKED_DOMAINS`. Override requires `--i-own-this-site` plus a typed confirmation.

**Breakpoint** — A CSS media query threshold (e.g. 768px). Extracted from `@media` rules by `scripts/analyze_dna.py:extract_breakpoints`.

**BFS** — Breadth-first search. Used by the discover stage to find pages by following links from the seed URL outward, depth-limited.

---

## C

**Calibration** — The process of running the tool against a known reference site and adjusting tuning constants until output matches human expectation. Documented in [references/calibration.md](../references/calibration.md).

**Capture** — The output of the crawl stage for a single page: source HTML, rendered HTML, computed styles, screenshots, network log, a11y tree, metadata. One directory per page under `raw/pages/<slug>/`.

**Captures.json** — `raw/captures.json`. Index of all per-page captures with status and files.

**Chrome MCP** — The Model Context Protocol server that lets Claude drive a real Chrome browser. Used by the auth stage to handle interactive logins (SSO, password managers, 2FA). Falls back to headless Playwright once auth state is captured.

**Component pattern** — A repeated UI structure detected in the rendered DOM (e.g. all the product cards). Identified via structural signature hashing in `scripts/analyze_dna.py:detect_components`. Output in `analysis/component-patterns.json`.

**Computed style** — A CSS property's resolved value as seen by the browser, after the cascade. Captured by `browser_scripts/extract_computed_styles.js` via `window.getComputedStyle()`. Output per element in `raw/pages/<slug>/computed-styles.json`.

**Content-hash dedupe** — Storing assets by SHA-256 of their bytes (first 16 hex chars). If three pages reference the same logo, only one file lands on disk; the asset manifest records three references.

---

## D

**DDe** — Short for "DNA-website" in command output. Sometimes used in log lines.

**Design tokens** — A normalized representation of a design system: colors, type, spacing, radius, shadow, motion, breakpoints. Output in `analysis/design-tokens.json`. The shape conforms to the [W3C design tokens spec](https://design-tokens.github.io/community-group/format/) family with a few additions.

**Discover** — Pipeline stage 3. Finds URLs via sitemap.xml, robots.txt, BFS link following, and SPA route sniffing. Output: `raw/routes.json`.

**Doctor** — `scripts/doctor.py`. A diagnostic that verifies the environment (Python version, Playwright browsers, Node deps, write permissions) and reports each check green or red. Run before reporting bugs.

---

## E

**Egress sanitization** — The rule that every byte written to disk passes through a sanitization function that strips credentials, tokens, and PII. Implemented in `scripts/utils.py:sanitize_*`.

---

## F

**Fixture** — A reproducible test input. `tests/fixtures/tiny_site/` is the canonical fixture — a minimal HTML+CSS site used for integration tests.

---

## G

**GCD spacing** — The greatest common divisor of all spacing values in computed styles. Used to detect the design system's base unit (usually 4 or 8 px). See `scripts/analyze_dna.py:detect_spacing_base`.

---

## H

**Headed / headless** — Playwright modes. Headed = visible browser window (used for manual auth, debugging). Headless = no GUI (used for bulk crawl).

---

## I

**IA tree** — Information architecture tree. The nested hierarchy of pages on a site, derived from URLs and link relationships. Output in `analysis/ia-tree.json`.

**Inspector** — The local browser experience served by `scripts/serve.py` at http://localhost:7777. Lets you walk through every captured page with assets loaded locally. Built into `inspector/` directory in the output.

---

## J

**JSON line log** — Structured log format used by the orchestrator. Each line is a JSON object with timestamp, stage, level, message, and context. Easier to grep than free-form text.

---

## K

**K-means** — The clustering algorithm used for color grouping. Run in LAB color space for perceptual accuracy. Multiple k values tried (`K_CANDIDATES = [6, 8, 12, 16, 20]`); best chosen via silhouette score. See `scripts/analyze_dna.py:extract_colors`.

---

## L

**LAB color space** — A perceptually-uniform color space. Distance in LAB ≈ perceived color difference. Used for color clustering because RGB and HSL are not perceptually uniform.

---

## M

**Manifest** — A directory's authoritative index. `manifest.json` for the full run, `manifest.partial.json` for in-progress checkpoints, `asset_manifest.json` for assets.

**Manifest.partial.json** — Written incrementally as each page completes. If a run is interrupted, `--resume` reads this and skips already-completed pages.

**MCP** — Model Context Protocol. The protocol that lets Claude talk to external tools (Chrome, file systems, APIs). This tool uses Chrome MCP for interactive auth.

---

## N

**Network log** — Per-page record of network requests made during capture. Sanitized: auth headers, sensitive query params, JWT-looking values, and PII are stripped. Stored at `raw/pages/<slug>/network-log.json`.

**Neutral color** — A color with low saturation (`saturation < NEUTRAL_SATURATION_MAX`). Classified as part of the neutral scale (greys, off-whites, near-blacks) rather than brand or accent.

---

## O

**Origin** — URL origin: scheme + host + port. Same-origin filtering means we don't crawl across origins unless `--include-subdomains` is set (and even then, only across subdomains of the same registrable domain).

---

## P

**Preflight** — Pipeline stage 1. Checks blocked categories, robots.txt, prompts for confirmations. Refuses to proceed without explicit user OK on risky operations.

**Pydantic** — The Python library used for all data contracts in this tool. Every JSON file produced has a corresponding Pydantic model in `scripts/models.py`.

---

## R

**Rate limiter** — Token-bucket limiter at the asset and page levels. Default 2 req/s; configurable via `--rate-limit`.

**Rebrand layer** — `rebrand/` directory in the output. Contains token templates with placeholders (`{{BRAND_PRIMARY}}`), a swap-map from original to placeholder, and component templates. Editable; the user customizes for their own brand.

**Robots.txt** — Standard for telling crawlers what's allowed. Honored by default; overridable with `--ignore-robots` plus explicit confirmation.

**Run** — One execution of the pipeline. Each run produces one output directory.

---

## S

**SCHEMA_VERSION** — A string constant in `scripts/models.py`. Bumped on breaking changes to any data contract. Manifest records the schema version used to produce the run.

**SPA** — Single-page application. Sites where navigation doesn't reload the document. The discover stage handles these via `browser_scripts/extract_spa_routes.js`, which sniffs Next.js `__NEXT_DATA__`, Nuxt `__NUXT__`, and pushState/popstate hooks.

**Schema version** — See SCHEMA_VERSION.

**Slug** — URL-safe filename derived from a URL. `/blog/my-post` → `blog-my-post`. Collisions resolved by appending an 8-char hash.

**Snapshot test** — A test that compares output to a stored reference file (`tests/fixtures/tiny_site_expected_tokens.json` etc.). Used to detect unintentional changes to algorithm output.

**Storage state** — Playwright's serialized session: cookies, localStorage, sessionStorage. Exported after auth, loaded by headless contexts during crawl. Stored at `.session/storage_state.json` (mode 0600, gitignored).

**Stretching** — When a single color cluster spans too wide a hue range. The color algorithm rejects clusters with high intra-cluster delta-E and re-clusters with higher k.

**Swap map** — `rebrand/swap-map.json`. Maps original tokens (original hex colors, original font families) to placeholder tokens (`{{BRAND_PRIMARY}}`). Used by `build_rebrand` to produce templates.

---

## T

**Tiny site** — `tests/fixtures/tiny_site/`. Two HTML pages and a CSS file. The canonical test input.

**Token** — In this tool, "token" usually means a design token (a named value in the design system). Sometimes means an auth token in security contexts; the meaning is clear from context.

**Tuning constant** — A named module-level constant in `scripts/analyze_dna.py` that affects algorithm behavior. Examples: `K_CANDIDATES`, `NEUTRAL_SATURATION_MAX`. All listed and documented in [references/calibration.md](../references/calibration.md).

---

## V

**Verify session** — After auth, check that the session is actually valid by hitting an endpoint the auth profile specifies (`verify_session_url`) and matching a success pattern (`verify_session_success`). Catches silent auth failures.

**Viewport** — Browser window size. Default desktop 1280x800. `--mobile-also` adds a second capture at 375x812.

---

## W

**Wall-clock time** — Total elapsed real-world time from start to finish. The thing the user notices. Contrast with CPU time. Pipeline target: < 8 min for 50 pages.

---

## See also

- [references/dna_extraction.md](../references/dna_extraction.md) — algorithms and constants in detail
- [references/data_contracts.md](../references/data_contracts.md) — all JSON shapes
- [CLAUDE.md](../CLAUDE.md) — code conventions
