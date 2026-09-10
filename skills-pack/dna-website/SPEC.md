# DNA-website — Full Production Spec

> **Audience:** Claude Code (or any agent) implementing this from a clean slate.
> **Format:** Single source of truth document. References the in-repo files for details.
> **Status:** Scaffold complete — every file exists with full contracts, signatures, and algorithms. Implementations are stubbed where they need careful work, fully written where they're foundational. Goal: hand this to Claude Code and have a working tool in a few iterations.

---

## TL;DR

`/dna-website <url> --auth <profile>` extracts a website's full DNA — every route, asset, design token, and content piece — into a local directory you can browse offline and use as the spec for rebuilding with your own branding.

The tool is a Python pipeline with Node helpers. It runs as 8 sequential stages, each reading and writing well-typed JSON artifacts. Authentication uses Chrome MCP (when present) or headful Playwright. Credentials live in a gitignored `.dna-website.env` file — never in the slash command.

## Project structure (what's in this scaffold)

```
dna-website/
├── SKILL.md                    ← Production-ready, drop into ~/.claude/skills/
├── README.md
├── pyproject.toml              ← All Python deps pinned
├── package.json                ← Node deps for inspector + CSS tools
├── .gitignore
├── .dna-website.env.example    ← Credential template
│
├── scripts/                    ← Python pipeline (15 files)
│   ├── __init__.py
│   ├── run.py                  ← Orchestrator (Typer CLI)
│   ├── config.py               ← Config dataclass + auth profile loader
│   ├── models.py               ← All Pydantic models (data contracts)
│   ├── utils.py                ← URL handling, sanitization, hashing
│   ├── preflight.py            ← Blocked domains, robots.txt
│   ├── auth.py                 ← Chrome MCP + Playwright login
│   ├── discover.py             ← sitemap + robots + BFS + SPA sniff
│   ├── crawl.py                ← Per-page capture pipeline
│   ├── download_assets.py      ← Async asset pipeline with 2-phase retry
│   ├── analyze_dna.py          ← Color / type / spacing / etc. algorithms
│   ├── analyze_content.py      ← Content + IA inventory
│   ├── build_rebrand.py        ← Token templating + swap-map
│   ├── report.py               ← REPORT.md + inspector prep
│   └── serve.py                ← Inspector launcher
│
├── node_helpers/               ← Node helpers (3 files)
│   ├── inspector_server.mjs    ← Express server, serves the local inspector
│   ├── css_analyze.mjs         ← CSS AST via css-tree
│   └── font_inspect.mjs        ← Font metadata via fontkit
│
├── browser_scripts/            ← Injected into pages (4 files)
│   ├── extract_computed_styles.js
│   ├── extract_spa_routes.js
│   ├── extract_network_idle.js
│   └── infinite_scroll.js
│
├── templates/                  ← Jinja2 templates (5 files)
│   ├── report.md.j2
│   ├── rebrand_readme.md.j2
│   ├── inspector_index.html.j2
│   ├── inspector_page.html.j2
│   └── tokens.css.j2
│
├── references/                 ← The actual spec (5 docs)
│   ├── architecture.md         ← Pipeline + concurrency + filesystem layout
│   ├── auth_strategies.md      ← 5 login strategies + Chrome MCP shim
│   ├── dna_extraction.md       ← All token-extraction algorithms
│   ├── data_contracts.md       ← Every JSON schema, every file
│   └── troubleshooting.md      ← Known failure modes + mitigations
│
└── tests/
    ├── __init__.py
    ├── test_smoke.py           ← Sanitization, URL, slug, hash tests
    └── fixtures/tiny_site/     ← Local site for integration tests
        ├── index.html
        ├── about.html
        └── style.css
```

**Total: 41 files.** Read `references/architecture.md` first.

---

## The pipeline at a glance

```
preflight → auth → discover → crawl → download_assets
                                    → analyze_dna → analyze_content
                                    → build_rebrand → report
```

Each stage:
- Reads strict-typed inputs (Pydantic-validated)
- Writes strict-typed outputs to disk
- Is independently re-runnable (the orchestrator drives the sequence, but each module has a clean entry point)

See `references/architecture.md` for the full pipeline diagram with data flow and contracts.

---

## The slash command grammar

```
/dna-website <url> [options]

Options:
  --auth <profile>          # Use named profile from .dna-website.env
  --depth N                 # Max crawl depth (default 4)
  --max-pages N             # Hard cap (default 200)
  --max-asset-size MB       # Skip larger assets (default 50)
  --include-subdomains      # Crawl *.target.com
  --skip-assets             # Faster; design tokens only
  --mobile-also             # Add mobile viewport captures
  --output <dir>            # Default ./dna-output/<domain>-<timestamp>
  --resume                  # Continue from manifest.partial.json
  --ignore-robots           # Override robots.txt (prompts)
  --i-own-this-site         # Required for blocked-category domains
  --rate-limit N            # Requests/sec (default 2)
  --concurrency N           # Parallel browser contexts (default 3)
  --verbose
```

Credentials are NEVER in the command. Always in `.dna-website.env`. The slash command should never echo the username/password back.

---

## Hard rules (enforced everywhere)

1. **No credentials in any artifact except `.session/storage_state.json`** (gitignored, mode 0600).
2. **Network logs sanitize** Authorization, Cookie, Set-Cookie, api keys, JWT-shaped values, Stripe-shaped values. See `scripts/utils.py:sanitize_network_log`. Test coverage in `tests/test_smoke.py`.
3. **Respect robots.txt** unless `--ignore-robots` AND user confirms in an interactive prompt.
4. **Blocked-category domains** (banking, government, healthcare, dating) require `--i-own-this-site` AND a typed confirmation.
5. **Rate-limit by default** (2 req/sec). No bursting.
6. **This tool produces reference material only**, never deployable output. The rebrand layer outputs placeholders, not a publishable site.

---

## What's implemented vs. stubbed

### Fully implemented
- All Pydantic models (`scripts/models.py`)
- All utility functions including the security-critical sanitization (`scripts/utils.py`)
- Config + auth profile loading (`scripts/config.py`)
- Preflight (`scripts/preflight.py`)
- The orchestrator (`scripts/run.py`)
- Asset URL extraction from HTML/CSS (`scripts/download_assets.py`)
- Color extraction with LAB k-means and silhouette score (`scripts/analyze_dna.py`)
- Typography scale detection (`scripts/analyze_dna.py`)
- Spacing GCD detection (`scripts/analyze_dna.py`)
- Radius/shadow/motion clustering (`scripts/analyze_dna.py`)
- Component pattern detection with structural signatures (`scripts/analyze_dna.py`)
- Content inventory + IA tree (`scripts/analyze_content.py`)
- Rebrand token + content placeholder generation (`scripts/build_rebrand.py`)
- All browser scripts (`browser_scripts/*.js`)
- All Jinja templates (`templates/*.j2`)
- Inspector server (`node_helpers/inspector_server.mjs`)
- Smoke tests for security-critical paths (`tests/test_smoke.py`)

### Stubbed (function signatures + detailed docstrings, ready to fill in)
- Chrome MCP integration shim (see comment block at bottom of `scripts/auth.py`)
- TOTP-based 2FA automation (intentionally out of scope for v1)
- Per-page `manifest.partial.json` integration in `crawl.py` (basic stub is there)

### Where to start implementing
1. Run the smoke tests: `pytest tests/test_smoke.py` (they should pass on the scaffold as-is once Python deps install).
2. Wire up the Chrome MCP shim in `auth.py` using your actual MCP tool names.
3. Run an integration test against the tiny site fixture: serve it locally, run `python -m scripts.run http://localhost:8080`.
4. Iterate on `analyze_dna.py` against real sites — the algorithms are specified but the constants will want tuning.

---

## Where to read for what

| Question | Read this |
|---|---|
| How does the pipeline work end-to-end? | `references/architecture.md` |
| How do I handle login? | `references/auth_strategies.md` |
| How does color clustering work? | `references/dna_extraction.md` § 1 |
| How is the component-pattern detector implemented? | `references/dna_extraction.md` § 8 |
| What's the JSON shape of `<file>`? | `references/data_contracts.md` |
| The crawler 429'd / login broke / etc. | `references/troubleshooting.md` |
| What's the slash command? | `SKILL.md` |

---

## Performance budgets

For a 50-page authenticated site:
- Total wall-clock: < 8 minutes
- Crawl: ~3 minutes (depends on per-page wait strategy)
- Asset download: ~2 minutes (heavily depends on asset count)
- Analysis: < 1 minute
- Output size: < 200 MB

Blow past these substantially → profile. Usually the cause is per-page wait timeouts, not algorithms.

---

## How Claude Code should use this

1. Open `references/architecture.md`. Understand the 8 stages.
2. Open `scripts/models.py`. Internalize the data contracts.
3. Open `scripts/run.py`. See how the orchestrator wires stages together.
4. Pick a stage to implement or improve. Each is independently testable.
5. Don't change schemas without bumping `SCHEMA_VERSION` in `models.py` and updating `references/data_contracts.md`.
6. Run smoke tests before every commit.
7. The user has Chrome MCP available — use it for auth flows. Fall back to Playwright headful for everything else.

---

## What this tool is NOT

- Not a deployment tool. The output is a reference package, not a publishable site.
- Not a way to clone sites you don't own / have permission to. The preflight blocks several categories and prompts on robots violations.
- Not a CAPTCHA bypass or anti-bot defeater. Use a real session via Chrome MCP login.
- Not a backend cloner. APIs are inventoried by shape (keys preserved, values redacted) but not their server-side logic.

---

## When something doesn't work

`references/troubleshooting.md` is the answer. If it's not there, add it.
