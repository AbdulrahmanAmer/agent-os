# Prompts for Claude Code

> Copy-pasteable prompts for working through each milestone in [PLAN.md](../PLAN.md). One section per milestone. Each prompt is self-contained — paste it into a fresh Claude Code session and Claude has enough context to proceed.

---

## Conventions

- Each prompt assumes you've `cd`'d into the `dna-website/` repo root.
- Each prompt asks Claude Code to **read first, code second**. Don't skip the read step.
- Prompts end with an acceptance check Claude Code should run before declaring "done."
- If Claude Code hits a wall, it should stop and report — don't let it grind for 20 minutes on a question a human can answer in 30 seconds.

---

## M0 — Environment ready

```
Read INDEX.md, then SPEC.md, then CLAUDE.md. After reading, run:

  python -m venv .venv
  source .venv/bin/activate
  pip install -e .
  playwright install chromium
  npm install
  python -m scripts.doctor
  pytest tests/test_smoke.py -v

Report any failures. Do not modify code yet. If pyproject.toml or package.json has
issues, fix the manifest only — not the underlying code.

Acceptance: smoke tests pass, doctor reports all green.
```

---

## M1 — Models + utils solid

```
Read references/data_contracts.md and scripts/models.py end-to-end.
Read scripts/utils.py end-to-end, paying special attention to the sanitize_* functions.

Then:
1. Audit tests/test_models.py — every Pydantic model should have at least a round-trip
   test (dump + load reproduces the model exactly).
2. Add tests/test_sanitization_fuzz.py: generate 100 random payloads with embedded
   JWTs, API keys, bearer tokens, session cookies, passwords. Verify sanitize_*
   produces zero leakage. Use hypothesis or just random.choice on a corpus.
3. Run: pytest --cov=scripts.utils --cov=scripts.models

Acceptance: ≥95% coverage on utils.py, ≥90% on models.py. Fuzz test passes with
0 leaked tokens out of 100 trials.

If you find a real sanitization bug, fix it and report the find before moving on.
```

---

## M2 — Preflight + auth (manual cookie-paste)

```
Read references/auth_strategies.md and scripts/auth.py and scripts/preflight.py.

Then:
1. Add tests/test_preflight.py:
   - Public URL → returns OK without prompts
   - Banking domain → returns BLOCKED unless --i-own-this-site
   - robots.txt disallow → returns NEEDS_CONFIRMATION
2. Implement the cookie_paste strategy in scripts/auth.py: user pastes JSON cookies
   (from a browser DevTools Application tab dump), we convert to Playwright
   storage_state.json format.
3. Implement the manual strategy: launches headed Playwright, prints
   "Log in then press Enter," waits on stdin, exports storage_state.
4. Verify file mode 0600 on the storage_state.json output.

Acceptance: `python -m scripts.run http://localhost:8080 --auth tiny` succeeds
against the tiny_site fixture served via `python -m http.server`.

Do NOT implement automated form-fill yet. That's M11 territory after we have
real-world test sites.
```

---

## M3 — Discover + crawl (basic)

```
Read references/architecture.md § Pipeline stages, then scripts/discover.py
and scripts/crawl.py.

Then:
1. Run the existing test_integration_tiny_site.py. If it doesn't pass, debug to
   green before adding new tests.
2. Add tests/test_discover.py covering: sitemap.xml parsing, robots.txt extraction
   of allowed/disallowed paths, BFS depth limit, same-origin filtering.
3. Implement the manifest.partial.json checkpoint write in crawl.py: after each
   page completes, append to manifest.partial.json with status + slug + url.
4. Implement --resume: on startup, if manifest.partial.json exists in the output
   dir, skip already-completed pages.
5. Add a test that kills a crawl midway (using a fixture page that hangs) and
   verifies --resume picks up correctly.

Acceptance: tiny-site integration test passes < 30s. Resume test passes.
```

---

## M4 — Asset pipeline

```
Read scripts/download_assets.py end-to-end.

Then:
1. Extend tests/fixtures/tiny_site/ with:
   - An inline <img src="hero.png"> referencing a 200x100px PNG
   - A `background-image: url(bg.jpg)` in style.css
   - A Google Fonts <link> reference
2. Add tests/test_download_assets.py:
   - Extracts asset URLs from HTML AND from CSS files
   - Content-hash dedupe: same image referenced from 3 pages → 1 file on disk,
     3 entries in asset manifest
   - Oversized asset (mock 100MB): skipped with download_status="too_large"
   - 404'd asset: recorded with download_status="failed"
3. Verify the 2-phase fallback: kill the local HTTP server mid-run after some
   assets have already downloaded via aiohttp. Subsequent assets should fall
   back to Playwright fetch.

Acceptance: deterministic asset_manifest.json against the tiny-site fixture.
Snapshot it to tests/fixtures/tiny_site_expected_assets.json.
```

---

## M5 — Design DNA, phase 1 (color + typography)

```
This milestone is the hardest. Read references/dna_extraction.md § Color and
§ Typography end-to-end. Read scripts/analyze_dna.py.

Then:
1. Add tests/test_analyze_dna_color.py with synthetic computed-styles inputs:
   - 3 brand-blue elements + 20 neutral-grey elements → brand.primary = blue,
     neutrals filled
   - All-neutral page → brand block empty
   - Mixed greys + bright red CTA → accent.danger set
2. Add tests/test_analyze_dna_typography.py:
   - Three sizes {16, 20, 25} → scale_ratio = 1.25
   - Single family → display = body
3. Pick 5 real sites for calibration. Document expected outputs in
   references/calibration.md. Tune K_CANDIDATES, NEUTRAL_SATURATION_MAX, and
   BRAND_FREQ_MULTIPLIER until 4/5 sites' palettes pass human review.
4. Verify determinism: run the same input 3x, get identical output.

Acceptance: color tests pass, typography tests pass, calibration.md shows
documented tuning rationale, all 5 real-site outputs reviewed and recorded.

If you can't get to 4/5 acceptable, stop and report the failure modes — don't
chase tuning into the next milestone.
```

---

## M6 — Design DNA, phase 2 (spacing, radius, shadow, motion, breakpoints)

```
Read references/dna_extraction.md § Spacing through § Breakpoints.

Then:
1. Add tests/test_analyze_dna_layout.py with deterministic unit tests:
   - Spacing GCD from {4, 8, 16, 24, 32} → 4. From {8, 16, 24, 32} → 8.
   - Radius clustering: {8, 9, 10} → 1 bucket (mean 9). {8, 16} → 2 buckets.
   - Shadow merging: two shadows differing only in alpha by < SHADOW_MERGE_ALPHA_TOL → 1.
   - Motion: cluster transition durations to 2–4 named tokens.
2. Run against tiny-site fixture. Snapshot expected output to
   tests/fixtures/tiny_site_expected_tokens.json.

Acceptance: snapshot test passes. Manual review of 5 calibration sites' shadow
and motion tokens is "reasonable" (document review notes in calibration.md).
```

---

## M7 — Content + IA

```
Read scripts/analyze_content.py.

Then:
1. Add tests/test_analyze_content.py:
   - tiny-site home produces 2 sections (hero + features)
   - Hero captures H1, p, "Read more" CTA
   - Features section captures all 3 card headings
2. Add tests/test_ia_tree.py:
   - URLs /, /blog, /blog/p1, /blog/p2 → nested tree
   - Slug collision (two URLs hashing to same slug) → hash suffix appended
3. Snapshot content-inventory.json for tiny-site.

Acceptance: both test files pass. Snapshot matches across runs.
```

---

## M8 — Component patterns + icons

```
Read references/dna_extraction.md § Component patterns and § Icon library.

Then:
1. The tiny-site fixture has 3 .card elements with identical structure.
   Expected: 1 pattern with occurrence_count=3, role_guess="card".
2. Add 2 inline SVG icons to the fixture (arrow-right, check). Verify both
   end up in analysis/icons/inline/ with the right svg content.
3. Add tests/test_components.py:
   - Tiny-site → exactly 1 pattern
   - Synthetic input with 5 deeply-nested structures sharing only top-level
     signature → not grouped (depth limit prevents over-clustering)
4. Tune COMPONENT_RECURSION_DEPTH and COMPONENT_MIN_OCCURRENCE against an
   e-commerce calibration site. Document tuning in calibration.md.

Acceptance: tiny-site test passes deterministically. Real-site review:
component-patterns.json contains plausible `product-card`-like entries.
```

---

## M9 — Rebrand layer + REPORT

```
Read references/rebrand_workflow.md and scripts/build_rebrand.py and
scripts/report.py.

Then:
1. Add tests/test_build_rebrand.py:
   - swap-map.json maps brand colors → {{BRAND_PRIMARY}} etc.
   - Copy placeholders: count matches sections × (heading + paragraphs + ctas)
   - Round-trip: applying swap-map to original content reproduces template
2. Add tests/test_report.py:
   - REPORT.md renders without Jinja errors
   - Contains expected sections (Summary, Tokens, Pages, etc.)
   - Brand color from M5 appears in the rendered output
3. Run end-to-end against tiny-site. Open REPORT.md in a markdown viewer to
   visually verify formatting.

Acceptance: rebrand + report tests pass. End-to-end run on tiny-site produces
a REPORT.md that's readable and complete.
```

---

## M10 — Inspector

```
Read references/inspector.md, scripts/serve.py, node_helpers/inspector_server.mjs.

Then:
1. Run a real crawl (use a small public site, ≤10 pages).
2. Launch the inspector: `python -m scripts.serve <output-dir>`.
3. Manually walk through the checklist in references/inspector.md § Acceptance:
   - Index page renders with thumbnails for every captured page
   - Click thumbnail → loads rewritten HTML
   - All images render (asset path rewriting worked)
   - Top toolbar links work
   - "Back to index" returns to homepage
4. Add tests/test_inspector_build.py:
   - report.generate against fixtures
   - inspector/index.html exists and references all slugs
   - At least one rewritten page has <img src> pointing under ../../raw/assets/

Acceptance: manual checklist passes on 2 different real sites. Test passes.
```

---

## M11 — Chrome MCP integration

```
This is the trickiest milestone because it depends on the local environment's
Chrome MCP server. Read references/auth_strategies.md § Chrome MCP integration.

Then:
1. From within your environment, list the available Chrome MCP tools. Document
   each tool name and signature in references/auth_strategies.md.
2. Replace the stubbed shim at the bottom of scripts/auth.py with real calls:
   - navigate to login URL
   - wait for user to complete login in the visible Chrome window
   - extract cookies / storage state
   - convert to Playwright storage_state.json format
3. Test against an actual SaaS site you have access to. Pick one with SSO
   (Google Workspace login is a good test).
4. Add a manual test recipe to docs/EXAMPLES.md.
5. Audit: grep -ri "password\|secret\|token" <output-dir>/ — should return zero
   matches.

Acceptance: real authenticated crawl completes. Zero credential leakage.
Recipe written for future users.

If Chrome MCP tools aren't available in this environment, stop and document
the gap. Use the manual fallback (headed Playwright) instead.
```

---

## M12 — Hardening + polish

```
Read references/observability.md.

Then:
1. Rate-limiter stress test: run against a fixture with 200 pages at
   --rate-limit 5. Inspect network log timestamps. Verify never exceeds 5
   requests in any 1-second window.
2. Resume stress test: kill a 50-page crawl at page 25 (use a fixture).
   Re-run with --resume. Verify pages 1-24 not re-crawled, 25-50 are.
3. Error message audit: every `raise` and `log.error` in scripts/ should
   name the URL and stage. Add tests/test_error_messages.py that scans for
   bare error strings and fails the build if any are found.
4. --verbose output: structured, color-coded via rich, shows stage progress
   with timestamps and rates.
5. Profile a 50-page real-site run with cProfile. Identify the top 3 slow
   paths. Optimize each by ≥30%. Document the wins in CHANGELOG.

Acceptance: < 8 minutes for 50-page site on typical broadband. Resume works
on every stage boundary.
```

---

## M13 — Release readiness

```
Final pass.

1. Review every references/*.md against the actual code. Update anything stale.
2. Write 3 real recipes in docs/EXAMPLES.md (replace any stubs with real
   captured output from sites you've tested).
3. Update docs/CHANGELOG.md with v0.1.0 — list every milestone delivered, every
   tuning constant chosen, every known limitation.
4. Run the full suite: `make test`. All green.
5. Run `make smoke` from a fresh clone in a clean directory. Verify under 10
   minutes total install + smoke.
6. Tag v0.1.0.

Acceptance: a new user can clone, install, and complete the QUICKSTART in
< 15 minutes total.
```

---

## Anti-patterns Claude Code should refuse

- **"Just add a try/except to make the test pass"** — diagnose the real bug.
- **"Comment out the failing assertion"** — fix the implementation.
- **"Add a constant and tune it later"** — every constant gets documented in calibration.md.
- **"Skip the test, the function is obvious"** — every function in scripts/ has tests.
- **"Disable robots.txt check for this test"** — use the tiny_site fixture instead.
- **"Hardcode the credentials for now"** — use a fixture profile in tests/fixtures/.

---

## When to bail and ask the human

- Algorithm tuning produces non-deterministic output across 3 runs.
- A milestone's acceptance test conflicts with what the implementation discovers.
- You find a security issue anywhere (sanitization gap, credential leak, missing rate limit).
- Chrome MCP tools aren't available in the environment.
- A real site's anti-bot defenses can't be respected without bypassing them.

Stop, report, wait. Don't grind.
