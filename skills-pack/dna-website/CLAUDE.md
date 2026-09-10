# CLAUDE.md

> Conventions for Claude Code (or any agent) working on this codebase.
>
> Read this once before your first edit. Re-read the relevant section before each milestone.

---

## Project mental model

This is a **pipeline tool** that takes a URL and produces a directory of artifacts. Every stage reads strict-typed JSON and writes strict-typed JSON. The whole thing is built around three properties:

1. **Reproducibility** — same input → same output (modulo network variability)
2. **Inspectability** — every intermediate artifact is on disk in a readable format
3. **Resumability** — any stage can pick up from `manifest.partial.json`

If you find yourself wanting to introduce shared mutable state, internal caches that aren't visible in the output directory, or non-deterministic behavior, **stop and reconsider**. There is almost always a way to express it through the artifact pipeline.

---

## Code conventions

### Python

- **Python 3.11+.** Use the new union syntax (`int | None`), `match` statements, `from __future__ import annotations`.
- **Type hints on everything public.** Internal helpers can skip them where obvious; functions in `models.py`, `utils.py`, and module-level entry points must have full annotations.
- **Pydantic v2** for all data contracts. No bare dicts crossing module boundaries.
- **Async everywhere I/O happens** (HTTP fetch, Playwright). Sync is fine for analysis stages — they're CPU-bound.
- **No global state.** Configuration flows top-down via `Config` instances. Logging is the one exception.
- **Logging > print.** Use `log = logging.getLogger(__name__)`. The orchestrator configures handlers.
- **Errors should name the URL and stage.** `raise RuntimeError(f"discover: sitemap fetch failed for {sm_url}: {e}")`, not just `raise RuntimeError("fetch failed")`.

### JavaScript

- ESM only (`*.mjs` for Node, plain `*.js` for browser scripts).
- No bundlers, no TypeScript. Browser scripts are injected as-is via Playwright.
- Browser scripts always wrap in an IIFE and assign to `window.__DNA_*` namespaces so multiple injections don't collide.

### File layout

- `scripts/` — Python pipeline. One file per stage. Plus `models.py`, `utils.py`, `config.py`, `run.py`.
- `node_helpers/` — Node helpers. Called by Python via subprocess, OR launched standalone by the user (inspector).
- `browser_scripts/` — Code injected into pages via Playwright. Pure browser environment.
- `references/` — The spec. Read this before changing algorithms.
- `templates/` — Jinja2.
- `tests/` — `test_<module>.py` mirrors `scripts/<module>.py`.

---

## How to add a feature

1. Find the milestone in `PLAN.md` it belongs to. If none fits, talk to the human.
2. Open the relevant `references/*.md`. Update it first, before code.
3. Open `references/data_contracts.md`. If a new field is needed, add it to the schema doc *and* `scripts/models.py` *and* bump `SCHEMA_VERSION`.
4. Write the test in `tests/test_<module>.py` first. Make it fail.
5. Implement. Make it pass.
6. Run the full smoke suite. Make it stay green.
7. Update `docs/CHANGELOG.md` under "Unreleased."

## How to fix a bug

1. Reproduce. Capture the failing input as a fixture in `tests/fixtures/`.
2. Write a test that reproduces the bug. Make it fail.
3. Fix. Make it pass. Make sure the smoke tests stay green.
4. If the bug is in sanitization (`scripts/utils.py`), add a fuzz test entry.
5. Add a `docs/CHANGELOG.md` "Fixed" entry.

---

## What to never do

- **Never put credentials in any artifact** other than `.session/storage_state.json`. Sanitize *before* writing.
- **Never call `requests` synchronously in an async path.** Use `aiohttp`.
- **Never extend a Pydantic model with a non-Optional field without bumping `SCHEMA_VERSION`** and writing a migration entry.
- **Never break the contract that `RunManifest.completed_stages` lists stages in execution order.** Downstream tools rely on this.
- **Never disable a sanitization rule to make a test pass.** The test is right.
- **Never `git add` an `.env` or `.session/` directory.** The pre-commit hook should catch this; if it doesn't, fix the hook first.

---

## Triggering rules of thumb (Claude Code specific)

- **Reading first, writing second.** Before editing any file, read every file it imports from and every file that imports it.
- **No "wait for user feedback" stalls.** If you're 90% sure about a tuning constant, write it down with a comment explaining the choice and move on. The human will rebalance later.
- **Use `references/troubleshooting.md` as a journal.** When you encounter a failure mode that takes >15 minutes to diagnose, add an entry.
- **Don't fight Pydantic.** If you can't get a model to validate, the model is probably right and your input is wrong.
- **Profile before optimizing.** `scripts/analyze_dna.py` is the heaviest path — anything in there is fair game for optimization. Everything else is I/O bound; CPU optimization is wasted work.

---

## When milestones disagree with reality

PLAN.md is the plan. Reality is reality. If a milestone's acceptance criteria turn out to be wrong (wrong test, wrong threshold, wrong order), **update PLAN.md** in the same PR as your code change. Don't leave a stale plan around.

---

## Communication

- Commit messages: imperative present tense. `Add color clustering` not `Added` or `Adds`.
- Each commit should be self-contained — passing tests at every commit on the main branch.
- PR descriptions: link to the milestone, list any acceptance-criteria deviations, attach output of `make test`.
- When in doubt, mark TODOs with `# TODO(M5): rationale` so the planning context is preserved.
