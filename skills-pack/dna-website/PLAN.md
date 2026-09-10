# Implementation Plan — DNA-website

> This is the build plan. It exists to take the scaffold from "structure with stubs" to "production tool" in a deterministic, verifiable sequence. Each milestone has an entry criterion, a definition of done, and an acceptance test.
>
> If you are Claude Code: follow these milestones in order. Do not skip ahead. Each milestone produces a runnable, testable artifact.

---

## Milestone map

```
M0  ── Environment ready          (verify deps install, smoke tests pass)
M1  ── Models + utils solid        (every contract testable in isolation)
M2  ── Preflight + auth (manual)   (can log in with cookie paste)
M3  ── Discover + crawl (basic)    (can crawl tiny_site fixture)
M4  ── Asset pipeline              (assets download, dedupe, classify)
M5  ── Design DNA — phase 1        (color + typography produce stable output)
M6  ── Design DNA — phase 2        (spacing, radius, shadow, motion, breakpoints)
M7  ── Content + IA                (content-inventory matches fixture exactly)
M8  ── Component patterns + icons  (3 cards in fixture detected as one pattern)
M9  ── Rebrand layer + REPORT      (REPORT.md renders end-to-end on fixture)
M10 ── Inspector                   (local browser experience usable)
M11 ── Chrome MCP integration      (real auth flow against an actual site)
M12 ── Hardening + polish          (rate limits, resume, --verbose, errors)
M13 ── Release readiness           (docs reviewed, CHANGELOG.md updated)
```

Estimated cumulative effort: 40–60 hours for an experienced engineer working with Claude Code on autopilot. Heavier on M5–M8 (algorithm tuning) than the rest.

---

## M0 — Environment ready

**Entry criterion:** You've checked the scaffold out into a clean directory.

**Tasks:**
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -e .` (reads `pyproject.toml`)
3. `playwright install chromium`
4. `npm install` (reads `package.json`)
5. `pytest tests/test_smoke.py -v`
6. `python -m scripts.doctor`  ← validates env, prints diagnostic

**Done when:** All 25+ smoke tests green. `doctor` reports OK on all checks.

**Acceptance:**
```
$ make smoke
✓ python deps installed
✓ playwright browsers installed
✓ node deps installed
✓ smoke tests passing (25/25)
✓ doctor: all green
```

---

## M1 — Models + utils solid

**Entry criterion:** M0 complete.

**Tasks:**
1. Add `tests/test_models.py` covering: model_dump round-trips, optional fields, version constant.
2. Audit `scripts/utils.py` sanitization with a fuzz test (`tests/test_sanitization_fuzz.py` — apply 100 random payloads with embedded JWTs/keys and verify zero leakage).
3. Confirm `SCHEMA_VERSION` is referenced in `run.py` final manifest.
4. Confirm `relative_to_output` returns POSIX paths on all OSes (Windows path separator gotcha).

**Done when:** Test count ≥ 50. Coverage of `utils.py` ≥ 95%. `models.py` ≥ 90%.

**Acceptance:**
```
$ pytest --cov=scripts.utils --cov=scripts.models
... 95%+ on both
```

---

## M2 — Preflight + auth (manual cookie-paste)

**Entry criterion:** M1 complete.

**Tasks:**
1. Test preflight against:
   - Public site (should pass without prompts) ← `tests/fixtures/tiny_site/` served locally
   - robots.txt-disallowed path (should prompt, then proceed/refuse based on input)
   - Blocked-category domain (should refuse without `--i-own-this-site`)
2. Implement and verify the `cookie_paste` auth strategy in `scripts/auth.py`. The user pastes a JSON cookie dump; we convert to Playwright storage_state format.
3. Implement and verify the `manual` strategy: opens a headed browser, prints "log in then press Enter," waits for user input, exports storage_state.

**Done when:**
- `python -m scripts.run http://localhost:8080 --auth tiny` succeeds against the local fixture
- `.session/storage_state.json` is created with mode 0600
- The storage state can be loaded by Playwright in a fresh context

**Acceptance test:** `tests/test_integration_auth_manual.py` (TODO file to create).

---

## M3 — Discover + crawl (basic)

**Entry criterion:** M2 complete.

**Tasks:**
1. Add `tests/test_discover.py`:
   - sitemap parsing returns expected URLs from a fixture XML
   - robots.txt extraction works
   - BFS respects depth limit
2. Add a minimal `tests/test_integration_tiny_site.py` that:
   - Spawns a local server hosting `tests/fixtures/tiny_site/`
   - Runs the orchestrator with `--max-pages 2`
   - Asserts `routes.json` contains both pages
   - Asserts `captures.json` has 2 entries, status=ok
   - Asserts both pages have `rendered.html`, `screenshot.desktop.png`, `computed-styles.json`
3. Implement `manifest.partial.json` checkpoint write/read in `crawl.py` and a corresponding `--resume` integration test.

**Done when:** Tiny-site integration test passes and runs in < 30 seconds.

**Acceptance:**
```
$ pytest tests/test_integration_tiny_site.py -v
... PASSED in 24.3s
```

---

## M4 — Asset pipeline

**Entry criterion:** M3 complete.

**Tasks:**
1. Extend the tiny-site fixture with an inline image and a Google Font reference.
2. Add `tests/test_download_assets.py`:
   - Asset URLs extracted from HTML + CSS
   - Content-hash dedupe across two captures that reference the same image
   - Oversized-asset skip works
   - 404'd asset is recorded with `download_status="failed"`
3. Verify the 2-phase fallback works: stop the local HTTP server mid-run, confirm Playwright fallback catches the gap.

**Done when:** `asset_manifest.json` reports expected counts on the tiny-site fixture (deterministic).

---

## M5 — Design DNA — phase 1 (color + typography)

**Entry criterion:** M4 complete.

**Tasks:**
1. Add `tests/test_analyze_dna_color.py` with synthetic computed-styles fixtures:
   - 3 brand-blue elements + 20 neutral-grey elements → expects `brand.primary = blue`, neutrals filled
   - All-neutral page → expects empty brand block
   - Mixed grayscale + bright red CTA → expects `accent.danger`
2. Add `tests/test_analyze_dna_typography.py`:
   - Three sizes in 1.25 ratio → expects `scale.ratio = 1.25`
   - Single font family → only `body` filled
3. Tune `K_CANDIDATES`, `SILHOUETTE_SAMPLE_FRAC`, `NEUTRAL_SATURATION_MAX` against 5 real sites' captured-styles dumps. Document the choice in `references/dna_extraction.md`.

**Done when:**
- Color tests deterministic across 3 runs (same input → identical output)
- Typography tests pass
- A manual run against a real site produces a `color-palette.json` that a human reviewer agrees with on 4/5 cluster classifications

**Calibration set:** Pick 5 well-known sites with public marketing pages and document expected outputs in `references/calibration.md` (M5 will produce this file).

---

## M6 — Design DNA — phase 2 (spacing, radius, shadow, motion, breakpoints)

**Entry criterion:** M5 complete.

**Tasks:**
1. Add deterministic unit tests for each algorithm in `tests/test_analyze_dna_layout.py`:
   - Spacing GCD finds 4px from {4, 8, 16, 24, 32}; finds 8px from {8, 16, 24, 32}
   - Radius clustering deduplicates {8, 9, 10} to a single bucket
   - Shadow merging treats two shadows differing only in alpha by 1% as one
2. Run against the tiny-site fixture and snapshot expected output to `tests/fixtures/tiny_site_expected_tokens.json`. Subsequent runs must match snapshot exactly.

**Done when:** Snapshot test passes; manual review of 5 real sites' shadow/motion tokens is "reasonable."

---

## M7 — Content + IA

**Entry criterion:** M6 complete.

**Tasks:**
1. `tests/test_analyze_content.py`:
   - Tiny-site fixture's home page produces 2 sections (hero + features)
   - Hero section captures the H1, paragraph, and the "Read more" CTA
   - Features section captures all 3 card headings
2. `tests/test_ia_tree.py`:
   - `/`, `/blog`, `/blog/post-1`, `/blog/post-2` → expected nested tree
   - Slug collision (two URLs producing same slug) handled by appending hash suffix

**Done when:** Both test files pass. The fixture's `content-inventory.json` is also snapshotted and must match.

---

## M8 — Component patterns + icons

**Entry criterion:** M7 complete.

**Tasks:**
1. The tiny-site fixture has 3 `.card` elements with identical structure. Expected: exactly one component pattern with `occurrence_count=3` and `role_guess="card"`.
2. Add `tests/test_components.py` verifying this.
3. Tune `COMPONENT_RECURSION_DEPTH` and `COMPONENT_MIN_OCCURRENCE` against a real e-commerce site (where you'd expect many `product-card` matches).
4. Inline-SVG icon detection: add 2 inline SVGs to the fixture and confirm both end up in `analysis/icons/`.

**Done when:** Component test asserts exact pattern count = 1 on the fixture. Icon test asserts 2 SVGs extracted.

---

## M9 — Rebrand layer + REPORT

**Entry criterion:** M8 complete.

**Tasks:**
1. `tests/test_build_rebrand.py`:
   - `swap-map.json` contains original brand color → `{{BRAND_PRIMARY}}` mapping
   - Number of copy placeholders matches: titles + descriptions + sections × (heading + paragraphs + ctas)
   - Round-trip: applying the swap map to the original content reproduces the template content
2. `tests/test_report.py`:
   - REPORT.md renders without Jinja errors
   - Contains the expected sections (Summary, Design tokens, Pages, etc.)
   - The brand color from M5 appears in the rendered output

**Done when:** A run against tiny-site produces a REPORT.md that opens cleanly in any markdown viewer.

---

## M10 — Inspector

**Entry criterion:** M9 complete.

**Tasks:**
1. Run a real crawl, launch the inspector: `python -m scripts.serve dna-output/<run>`
2. Manual checklist (`references/inspector.md` § acceptance):
   - Index page renders with thumbnails for every captured page
   - Clicking a thumbnail loads the rewritten HTML
   - All images render (paths rewrote correctly)
   - Top toolbar links work (source/rendered/styles/network)
   - "Back to index" returns to the homepage
3. Add `tests/test_inspector_build.py` that:
   - Runs `report.generate` against fixtures
   - Asserts `inspector/index.html` exists and references all expected slugs
   - Asserts at least one rewritten page has its `<img src>` pointing at a relative path under `../../raw/assets/`

**Done when:** Manual checklist passes on 2 different real sites. Inspector test passes.

---

## M11 — Chrome MCP integration

**Entry criterion:** M10 complete.

**Tasks:**
1. Read your environment's Chrome MCP tool listing. Identify the tool names for navigate, screenshot, get-cookies (or storage state).
2. Replace the stubbed Chrome MCP shim at the bottom of `scripts/auth.py` with real calls.
3. Test the full flow: user types `/dna-website https://docs.somecompany.com --auth somecompany` → tool opens Chrome → user completes SSO → tool exports session → headless crawl proceeds.
4. Add a manual test recipe to `docs/EXAMPLES.md`.

**Done when:** A real authenticated crawl completes with session captured via Chrome MCP. No credential leakage in any output file.

---

## M12 — Hardening + polish

**Entry criterion:** M11 complete.

**Tasks:**
1. Rate-limiter stress test: run against a site with 200 pages at `--rate-limit 5`. Verify never exceeds 5 req/s in any 1-second window (use the network log to check).
2. `--resume` end-to-end: kill a 50-page crawl at page 25. Re-run with `--resume`. Verify only pages 25–50 are re-crawled.
3. Error message audit: every `raise` and every `log.error` in `scripts/` should produce a message that names the URL, the stage, and the cause. Add an `errors.md` table.
4. `--verbose` output: structured, color-coded, shows stage progress with timestamps.
5. Profile a 50-page real-site run. Identify the top 3 slow paths. Optimize each by ≥ 30%.

**Done when:** Performance budget met (< 8 minutes for 50-page site). Resume works.

---

## M13 — Release readiness

**Entry criterion:** M12 complete.

**Tasks:**
1. Review every `references/*.md` for accuracy against the actual code.
2. Write 3 real recipes in `docs/EXAMPLES.md` (one each for: public marketing site, authenticated dashboard, e-commerce).
3. Update `docs/CHANGELOG.md` with v0.1.0 entry.
4. Run the whole test suite, smoke-deploy, doctor — all green.
5. Tag v0.1.0.

**Done when:** A new user can install from scratch in < 10 minutes and run a useful crawl in < 5.

---

## Acceptance criteria, system-wide

When all 13 milestones are complete, the following should all be true:

| Criterion | How to verify |
|---|---|
| `make test` runs the full suite < 90s | `time make test` |
| Coverage > 80% on `scripts/` | `pytest --cov=scripts` |
| Doctor reports all green on a fresh install | `python -m scripts.doctor` |
| Tiny-site integration test < 30s | `pytest tests/test_integration_tiny_site.py` |
| Real-site (50 pages) crawl < 8 min | manual |
| No credential strings appear in any artifact (grep test) | `grep -r "password\|api[_-]key\|bearer" dna-output/<run>` returns 0 hits |
| All 8 stages can resume from `manifest.partial.json` | manual test, kill mid-stage |
| Inspector renders 1 real site correctly | manual |

---

## Working with Claude Code

When you (Claude Code) pick up a milestone, follow this loop:

1. **Read the relevant references/** doc end-to-end. Don't skim.
2. **Read the existing code** for the module you're touching. Find what's stubbed.
3. **Write the test first.** Add to the milestone's named test file.
4. **Run only that test** in watch mode while implementing.
5. **Run the smoke tests** before committing the milestone.
6. **Update PLAN.md** with the milestone's actual completion date and any deviations from this plan.
7. **Update CHANGELOG.md** under "Unreleased" with the change.

Bail out and ask the human:
- If a milestone's acceptance criteria conflict with what you're discovering.
- If a tuning constant in `analyze_dna.py` produces non-deterministic output across runs.
- If you find a security issue (anywhere — sanitization, credential leak, etc.) — stop and flag immediately.

Never:
- Skip writing tests because "the code looks obviously right."
- Bump `SCHEMA_VERSION` without writing a migration entry in `references/data_contracts.md`.
- Disable a security check to make a test pass.
- Commit anything with `.env` files in it. The pre-commit hook should block this — verify it works.
