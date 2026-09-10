# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Added 'unlimited' (0) semantics to `--max-pages` and `--depth`. Pass `0`
  (or omit a low cap) to let the BFS frontier run to convergence. Removed any
  hardcoded count caps from `scripts/discover.py` (sitemap, robots, BFS, SPA
  sniff are all retained in full) and from `scripts/download_assets.py`
  (per-asset size cap kept; asset-count cap removed).
- `is_purchase_url()` in `scripts/utils.py` plus `PURCHASE_URL_PATTERNS`
  blocklist (paths and `action=` query values). Wired into preflight,
  discover, and crawl as defense in depth. Skipped URLs are recorded with
  `status="skipped_purchase_url"` in the capture manifest. New test suite
  `tests/test_no_purchase.py` covers 30+ positive and negative samples plus
  element-text classification.
- `manifest.partial.json` is now written after EVERY page (success, failure,
  or skipped_purchase_url) so `--resume` picks up cleanly after any
  interruption. Payload includes both completed slugs and the live capture
  list.
- `AuthProfile` schema accepts the lowercase / strategy-based INI keys
  (`url`, `strategy`, `login_url`, `email`, `password`,
  `post_login_url_pattern`, `verify_session_url`, `verify_session_success`).
  Legacy UPPERCASE keys still work for backward compat.
- Initial scaffold: 8-stage pipeline (preflight → auth → discover → crawl → assets → analyze_dna → analyze_content → build_rebrand → report)
- Pydantic data contracts for every artifact (`scripts/models.py`)
- Sanitization layer covering headers, JSON, URLs, and token-shaped values (`scripts/utils.py`)
- Color extraction via LAB k-means with silhouette scoring (`scripts/analyze_dna.py`)
- Typography scale detection
- Spacing GCD detection
- Component pattern detection via structural signatures
- Inline-SVG icon library extraction
- Rebrand layer with placeholder generation and swap-map
- Inspector — local Express server for browsing captures offline
- Smoke + unit + integration test scaffolding
- Pre-commit hooks blocking `.env` and `.session/` commits
- GitHub Actions CI workflow
- Doctor script for environment validation
- Compare script for diffing two runs
- 5 reference docs (architecture, auth, dna_extraction, data_contracts, troubleshooting)
- 6 additional reference docs (security, development, rebrand_workflow, inspector, observability, calibration)
- INDEX.md — top-level map of the scaffold for readers, runners, and agents
- docs/QUICKSTART.md — 5-minute first-run guide
- docs/SAMPLE_OUTPUT.md — synthetic-but-realistic example of a run output (directory tree + REPORT.md + design-tokens.json + manifest.json)
- docs/PROMPTS.md — copy-paste prompts for Claude Code, one per milestone
- docs/GLOSSARY.md — terminology reference
- docs/FAQ.md — design-decision rationale (why LAB? why GCD? why Pydantic? why not deployable?)
- docs/RISK_REGISTER.md — 23 risks tracked with impact, likelihood, mitigation, status

### Security
- Hard-blocked categories: banking, government, healthcare, dating
- robots.txt respect by default
- Default rate limit of 2 req/s
- Credentials never written outside `.session/storage_state.json` (mode 0600)

### Known limitations
- Chrome MCP integration is stubbed (M11 milestone)
- TOTP-based 2FA is not automated
- Headless Playwright may fail on aggressive bot-protection sites; the `manual` auth strategy is the recommended fallback
- Component pattern detection has not been tuned on a large corpus; expect to revisit thresholds

---

## [0.1.0] — Unreleased

_First public release. Targets the M13 acceptance criteria in PLAN.md._
