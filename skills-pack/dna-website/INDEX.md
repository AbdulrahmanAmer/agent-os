# Index — what's in this scaffold and where to start

> Read this first if you've never seen this repo before. It maps every file to its purpose.

---

## I'm a human evaluating this scaffold

Start here:
1. **[SPEC.md](SPEC.md)** — what this tool does, what it produces, what it doesn't do
2. **[docs/SAMPLE_OUTPUT.md](docs/SAMPLE_OUTPUT.md)** — what a real run produces, file by file
3. **[docs/EXAMPLES.md](docs/EXAMPLES.md)** — five worked recipes (public site, dashboard, e-commerce, single page, change tracking)
4. **[docs/FAQ.md](docs/FAQ.md)** — the questions that come up on first read

That's ~30 minutes and you'll know whether this is the right tool for your situation.

## I'm running this for the first time

1. **[docs/QUICKSTART.md](docs/QUICKSTART.md)** — five minutes, public site, no auth
2. **[README.md](README.md)** — install and CLI reference
3. **[docs/EXAMPLES.md](docs/EXAMPLES.md)** — pick the recipe closest to your situation

## I'm Claude Code (or another agent) implementing this

1. **[CLAUDE.md](CLAUDE.md)** — code conventions, style, gotchas. Read this once cold.
2. **[PLAN.md](PLAN.md)** — 13 milestones from "scaffold" to "v0.1.0". Work milestones in order.
3. **[docs/PROMPTS.md](docs/PROMPTS.md)** — copy-pasteable prompts for each milestone.
4. **[references/architecture.md](references/architecture.md)** — pipeline data flow, contracts.
5. **[references/dna_extraction.md](references/dna_extraction.md)** — every algorithm, every tuning constant, every edge case.

When stuck:
- **[references/troubleshooting.md](references/troubleshooting.md)** — known failure modes
- **[docs/RISK_REGISTER.md](docs/RISK_REGISTER.md)** — what can go wrong; what mitigations exist
- **[docs/GLOSSARY.md](docs/GLOSSARY.md)** — terms

## I'm a security reviewer

1. **[references/security.md](references/security.md)** — threat model, sanitization rules, blocked categories
2. **[scripts/utils.py](scripts/utils.py)** — `sanitize_*` functions; this is where the rubber meets the road
3. **[scripts/preflight.py](scripts/preflight.py)** — domain blocking, confirmation prompts
4. **[.dna-website.env.example](.dna-website.env.example)** — credential schema (the actual file is gitignored)
5. **[.gitignore](.gitignore)** + **[.pre-commit-config.yaml](.pre-commit-config.yaml)** — defense in depth against committing secrets

---

## Top-level files

| File | Purpose |
|---|---|
| [SKILL.md](SKILL.md) | Skill manifest. Drop into `~/.claude/skills/` to activate. |
| [SPEC.md](SPEC.md) | Full production spec — single source of truth for what this tool is |
| [PLAN.md](PLAN.md) | 13-milestone build plan with acceptance criteria |
| [CLAUDE.md](CLAUDE.md) | Code conventions for any agent working on this |
| [INDEX.md](INDEX.md) | This file |
| [README.md](README.md) | Install + CLI quickstart |
| [Makefile](Makefile) | `make install / test / smoke / clean / lint` |
| [pyproject.toml](pyproject.toml) | Python deps (pinned), entry points |
| [package.json](package.json) | Node deps for inspector + CSS analysis |
| [.dna-website.env.example](.dna-website.env.example) | Auth profile template |
| [.gitignore](.gitignore) | Outputs, sessions, env files |
| [.editorconfig](.editorconfig) | Whitespace conventions |
| [.pre-commit-config.yaml](.pre-commit-config.yaml) | Block secrets; ruff; black |
| [ruff.toml](ruff.toml) | Lint config |

## scripts/ — Python pipeline

| File | Stage | Purpose |
|---|---|---|
| [run.py](scripts/run.py) | orchestrator | Typer CLI; runs all 8 stages in order |
| [config.py](scripts/config.py) | — | Config dataclass + auth profile loading |
| [models.py](scripts/models.py) | — | All Pydantic models (data contracts) |
| [utils.py](scripts/utils.py) | — | URL handling, hashing, **sanitization** |
| [preflight.py](scripts/preflight.py) | 1 | Blocked domains, robots.txt, confirmations |
| [auth.py](scripts/auth.py) | 2 | Chrome MCP + Playwright login; storage_state export |
| [discover.py](scripts/discover.py) | 3 | sitemap + robots + BFS + SPA route sniffing |
| [crawl.py](scripts/crawl.py) | 4 | Per-page: source/rendered HTML, styles, screenshots, network |
| [download_assets.py](scripts/download_assets.py) | 5 | Async asset pipeline; content-hash dedupe; 2-phase fallback |
| [analyze_dna.py](scripts/analyze_dna.py) | 6 | Colors, type, spacing, radii, shadows, motion, breakpoints, components |
| [analyze_content.py](scripts/analyze_content.py) | 7 | Copy inventory + IA tree |
| [build_rebrand.py](scripts/build_rebrand.py) | 8 | Token template + swap-map.json |
| [report.py](scripts/report.py) | 8 | REPORT.md + inspector prep |
| [serve.py](scripts/serve.py) | post-run | Wraps the Node inspector server |
| [doctor.py](scripts/doctor.py) | diagnostic | Verifies env, deps, browser; prints a green check report |
| [compare.py](scripts/compare.py) | post-run | Diff two output directories (track changes over time) |

## browser_scripts/ — Playwright-injected scripts

| File | Purpose |
|---|---|
| [extract_computed_styles.js](browser_scripts/extract_computed_styles.js) | Walks rendered DOM; emits typed styles per element |
| [extract_spa_routes.js](browser_scripts/extract_spa_routes.js) | Hooks pushState/popstate; sniffs `__NEXT_DATA__`, `__NUXT__` |
| [extract_network_idle.js](browser_scripts/extract_network_idle.js) | Custom network-idle detector for SPA-heavy sites |
| [infinite_scroll.js](browser_scripts/infinite_scroll.js) | Scroll-to-stable-height loop, 30s cap |

## node_helpers/ — Node-side tools

| File | Purpose |
|---|---|
| [inspector_server.mjs](node_helpers/inspector_server.mjs) | Express server at localhost:7777 |
| [css_analyze.mjs](node_helpers/css_analyze.mjs) | CSS AST analysis via css-tree |
| [font_inspect.mjs](node_helpers/font_inspect.mjs) | Font metadata via fontkit |

## templates/ — Jinja2 templates

| File | Renders |
|---|---|
| [report.md.j2](templates/report.md.j2) | `REPORT.md` |
| [rebrand_readme.md.j2](templates/rebrand_readme.md.j2) | `rebrand/README.md` |
| [inspector_index.html.j2](templates/inspector_index.html.j2) | Inspector home with page thumbnails |
| [inspector_page.html.j2](templates/inspector_page.html.j2) | Per-page rewritten wrapper |
| [tokens.css.j2](templates/tokens.css.j2) | `rebrand/tokens.css` with CSS custom properties |

## references/ — algorithm + integration specs

| File | What it covers |
|---|---|
| [architecture.md](references/architecture.md) | Pipeline stages, data flow, file layout, contracts |
| [auth_strategies.md](references/auth_strategies.md) | 5 auth strategies, Chrome MCP integration, 2FA, fallback ladder |
| [dna_extraction.md](references/dna_extraction.md) | Every algorithm with constants and edge cases |
| [data_contracts.md](references/data_contracts.md) | JSON schemas for every output file |
| [security.md](references/security.md) | Threat model, sanitization spec, allowed/denied categories |
| [inspector.md](references/inspector.md) | Inspector UX, file layout, acceptance checklist |
| [rebrand_workflow.md](references/rebrand_workflow.md) | How a designer uses the rebrand layer |
| [calibration.md](references/calibration.md) | Tuning constants; calibration sites; review process |
| [observability.md](references/observability.md) | Logging, metrics, --verbose output format |
| [development.md](references/development.md) | Local dev loop, debugging tips |
| [troubleshooting.md](references/troubleshooting.md) | Known failure modes, mitigations |

## docs/ — reader-facing guides

| File | Audience |
|---|---|
| [QUICKSTART.md](docs/QUICKSTART.md) | First-time user |
| [EXAMPLES.md](docs/EXAMPLES.md) | Five worked recipes |
| [FAQ.md](docs/FAQ.md) | Design-decision rationale |
| [GLOSSARY.md](docs/GLOSSARY.md) | Terminology reference |
| [SAMPLE_OUTPUT.md](docs/SAMPLE_OUTPUT.md) | A realistic run output, tree and key file contents |
| [PROMPTS.md](docs/PROMPTS.md) | Copy-paste prompts for Claude Code per milestone |
| [RISK_REGISTER.md](docs/RISK_REGISTER.md) | What can go wrong; mitigations; status |
| [CHANGELOG.md](docs/CHANGELOG.md) | Version history |

## tests/ — test suite

| File | Coverage |
|---|---|
| [conftest.py](tests/conftest.py) | Shared fixtures (tiny_site server, sample data) |
| [test_smoke.py](tests/test_smoke.py) | Imports + basic API surfaces |
| [test_models.py](tests/test_models.py) | Pydantic round-trips, schema version |
| [test_analyze_dna.py](tests/test_analyze_dna.py) | Color, type, spacing, radius algorithms |
| [test_integration_tiny_site.py](tests/test_integration_tiny_site.py) | End-to-end against the local fixture |
| [fixtures/tiny_site/](tests/fixtures/tiny_site/) | Minimal HTML+CSS site for integration tests |

---

## Stats

```
$ scc dna-website/
─────────────────────────────────────────
Language    Files  Lines    Code  Comments
─────────────────────────────────────────
Python         16  ~4,400  3,300       450
Markdown       28  ~3,600  3,000         0
JavaScript      7    ~500    370        70
TOML/INI        4     ~80     65         5
─────────────────────────────────────────
Total         55+  ~8,600  6,700       525
```

(numbers approximate — run `scc .` for current)
