# Development guide

> Concrete steps for contributing to this codebase. Read `CLAUDE.md` first for conventions; read `PLAN.md` for what's in flight.

---

## Setup

```bash
git clone <repo>
cd dna-website
python -m venv .venv && source .venv/bin/activate
make install        # Python deps + Node deps + Playwright browsers
pre-commit install  # Wire up git hooks
make doctor         # Sanity check
make smoke          # Should be green
```

If `make doctor` reports issues, fix them before doing anything else.

---

## Daily workflow

```bash
# Start work
git checkout -b feature/m5-color-tuning

# Edit code...

# Tests in watch mode (separate terminal)
pytest tests/test_analyze_dna_color.py -v --looponfail

# Before committing
make lint
make smoke

# Commit
git add -p
git commit -m "Tune color silhouette threshold for low-saturation palettes"

# Before pushing
make test
git push
```

---

## Project layout cheatsheet

```
Module                       Purpose                              Run as
─────────────────────────────────────────────────────────────────────────────
scripts/run.py               Pipeline orchestrator                python -m scripts.run <url>
scripts/serve.py             Inspector launcher                   python -m scripts.serve <dir>
scripts/doctor.py            Env validator                        python -m scripts.doctor
scripts/compare.py           Diff two runs                        python -m scripts.compare <a> <b>

scripts/preflight.py         Stage 1                              (called by run.py)
scripts/auth.py              Stage 2
scripts/discover.py          Stage 3
scripts/crawl.py             Stage 4
scripts/download_assets.py   Stage 5
scripts/analyze_dna.py       Stage 6
scripts/analyze_content.py   Stage 7
scripts/build_rebrand.py     Stage 8a
scripts/report.py            Stage 8b

scripts/models.py            All Pydantic data contracts
scripts/utils.py             URL, hashing, sanitization
scripts/config.py            Config + auth profile loader
```

To add a new stage:
1. Pick a position in the pipeline. The orchestrator (`run.py`) defines the order.
2. Add models in `models.py`. Bump `SCHEMA_VERSION`.
3. Create `scripts/<stage>.py` with a top-level `run(config, *prior_artifacts) -> Artifact` function.
4. Wire it into `run.py`.
5. Add `references/<stage>.md` documenting the algorithm.
6. Add `tests/test_<stage>.py`.

---

## Tests

We have four flavors:

| Kind | Marker | Speed | When |
|---|---|---|---|
| Smoke | `tests/test_smoke.py` (no marker) | < 5s | Every commit |
| Unit | per module | < 60s | Every push |
| Integration | `@pytest.mark.integration` | < 5min | PR, nightly |
| Calibration | `@pytest.mark.calibration` | minutes | Manual, before release |

Pytest markers are declared in `pyproject.toml`. To skip slow tests during dev:

```bash
pytest -m "not integration and not calibration"
```

### Fixtures

`tests/fixtures/tiny_site/` is the reference site. It is intentionally small, deterministic, and never connected to the internet. If you need a new fixture:
- Add to `tests/fixtures/<name>/`
- If the fixture needs an HTTP server, use the `local_server` pytest fixture in `tests/conftest.py`
- Snapshot outputs go to `tests/fixtures/<name>_expected/`

---

## Debugging

### Run with verbose logging

```bash
python -m scripts.run https://example.com --verbose
```

`--verbose` enables DEBUG-level logging to both the console and `dna-output/<run>/run.log`.

### Inspect intermediate artifacts

Every stage writes its output to disk. You can re-run any single stage manually:

```python
from scripts.config import build_config
from scripts.models import load_model, CaptureManifest
import scripts.analyze_dna as dna

config = build_config(url="https://example.com", output_dir="dna-output/example-2026-05-11")
captures = load_model(config.output_dir / "captures.json", CaptureManifest)
tokens = dna.run(config)   # rewrites analysis/design-tokens.json
```

### Inspect a single page's capture

```bash
cd dna-output/<run>/raw/pages/<slug>/
ls -la
cat meta.json | jq
open screenshot.desktop.png
```

### Common pitfalls

| Symptom | Likely cause |
|---|---|
| `playwright._impl._api_types.Error: Browser closed.` | Headed browser was closed by the user mid-run. Re-run with `--resume`. |
| `pydantic.ValidationError` on load_model | Schema drift. Check `SCHEMA_VERSION` in the failing file vs `scripts/models.py`. |
| `aiohttp.ClientError: ... Cookie too large` | Auth profile has a stale session. Re-run auth. |
| Colors come out all neutrals | Likely the page renders with CSS-in-JS that wasn't fully loaded. Try `--page-timeout 60`. |

---

## Style decisions

These are firm. Don't change without team agreement.

- **No regex for HTML parsing.** Always BeautifulSoup or `css-tree`.
- **No `print()` in pipeline code.** Use logging.
- **No hardcoded credentials in code or tests.** Use environment variables or `.env.example`.
- **No `requests` library.** Async-only via `aiohttp`.
- **No `pickle`.** JSON only (via Pydantic).
- **No `pytest-bdd`, `unittest.mock` for HTTP, or `responses`.** Use `aioresponses` for aiohttp mocking; real Playwright runs for integration tests.

---

## Release process

1. All 13 milestones in `PLAN.md` checked off.
2. `make ci` green.
3. Update `docs/CHANGELOG.md`: move everything from `Unreleased` to a new version block.
4. Update version in `pyproject.toml`, `package.json`, `scripts/__init__.py`.
5. `git tag v0.1.0 && git push --tags`
6. Build artifacts: `python -m build`
7. Create GitHub release notes from CHANGELOG.

---

## Where to ask for help

- Stuck on an algorithm? → `references/dna_extraction.md`
- Stuck on architecture? → `references/architecture.md`
- Stuck on auth? → `references/auth_strategies.md`
- Found a bug nobody mentioned? → `references/troubleshooting.md` (add an entry)
- Code review? → tag a human, this is one of the high-risk tools where AI-only review is not sufficient
