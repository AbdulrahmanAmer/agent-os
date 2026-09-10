---
disable-model-invocation: true
name: dna-website
description: "Fire when an entire external site must be captured to disk to study or rebuild it - every route, asset and design token. Do NOT fire to look at a single page, where fetching it is enough, and never fire in order to lift copy, imagery or a section verbatim: a capture is reference material, not source. Explicit invocation only."
---

# DNA-website

Extracts a website's full DNA — routes, design system, assets, content — into a structured local package the user can inspect, rebrand, and rebuild from.

## When this skill triggers

- User types `/dna-website <url>` (with or without `--auth`, `--depth`, etc.)
- User asks to "clone a site", "mirror a site", "extract a website's design", "pull a website's DNA", "reverse-engineer this site"
- User wants to study an authenticated dashboard/admin area design they have legitimate access to

## Pre-flight checklist (do this BEFORE crawling)

1. **Confirm legitimacy.** Verify the user has the legal right to clone the target site (they own it, it's for personal study, or they have explicit permission). If it's not obvious from context, ask. Do not skip this step.
2. **Check the blocked-domains list** in `scripts/preflight.py`. If the target is in a blocked category (banking, government, healthcare, dating), require the `--i-own-this-site` flag plus one additional confirmation.
3. **Load credentials safely.** Look for a `.dna-website.env` file in the current working directory. If `--auth` is set but the profile is missing, prompt the user. **Never accept passwords inline in the slash command.**
4. **Read `references/architecture.md`** for the pipeline overview before writing any new code.

## Slash command grammar

```
/dna-website <url> [options]

Options:
  --auth <profile-name>     Use named auth profile from .dna-website.env
  --depth N                 Max crawl depth (default 4)
  --max-pages N             Hard cap on pages (default 200)
  --max-asset-size MB       Skip assets bigger than this (default 50)
  --include-subdomains      Crawl *.target.com (default: same-origin only)
  --skip-assets             Faster crawl, no binary downloads
  --mobile-also             Also capture mobile viewport
  --output <dir>            Output directory (default: ./dna-output/<domain>-<timestamp>)
  --resume                  Continue an interrupted crawl from manifest.partial.json
  --ignore-robots           Override robots.txt (asks for confirmation)
  --i-own-this-site         Required for blocked-category domains
  --rate-limit N            Requests per second (default 2)
  --concurrency N           Parallel page captures (default 3)
  --verbose                 More logging
```

## Workflow

When this skill triggers, do the following in order:

1. **Parse the slash command.** Extract URL and flags. Validate URL is well-formed and has scheme.
2. **Run preflight.** Call `python -m scripts.preflight <url> <flags>`. This handles domain blocking, robots.txt, and user confirmation prompts.
3. **Load credentials** if `--auth` is set. Read `.dna-website.env`. Never echo the password. Never log it.
4. **Execute the pipeline** by calling `python -m scripts.run <url> <flags>`. Stream stdout to the user — the orchestrator emits structured progress lines.
5. **On completion**, point the user at three artifacts:
   - `<output>/REPORT.md` — human-readable summary
   - `<output>/inspector/` — run `node node_helpers/inspector_server.mjs <output>/inspector` to browse
   - `<output>/rebrand/tokens.template.json` — editable design tokens

## Files in this skill

| File | Purpose |
|---|---|
| `scripts/run.py` | Orchestrator — start here when reading code |
| `scripts/preflight.py` | Domain check, robots.txt, blocked categories |
| `scripts/auth.py` | Chrome MCP login + session export |
| `scripts/discover.py` | Sitemap, robots, BFS crawl, SPA route sniff |
| `scripts/crawl.py` | Per-page capture (HTML, styles, screenshots, network) |
| `scripts/download_assets.py` | Asset pipeline with dedupe and rate limiting |
| `scripts/analyze_dna.py` | Color/type/spacing/radius/shadow/motion extraction |
| `scripts/analyze_content.py` | Copy and IA inventory |
| `scripts/build_rebrand.py` | Token templating + swap-map |
| `scripts/report.py` | REPORT.md generator |
| `scripts/serve.py` | Python wrapper for the Node inspector |
| `scripts/models.py` | Pydantic models — read this before touching any JSON I/O |
| `references/architecture.md` | Full pipeline, data flow, contracts |
| `references/auth_strategies.md` | Chrome MCP integration, 2FA, fallbacks |
| `references/dna_extraction.md` | Detailed algorithms for design-token derivation |
| `references/data_contracts.md` | JSON schemas for every output file |
| `references/troubleshooting.md` | Known failure modes and mitigations |

## When something goes wrong

- **Login fails** → see `references/auth_strategies.md` § "Fallback ladder"
- **Crawler gets 403/429** → see `references/troubleshooting.md` § "Anti-bot"
- **Asset hangs** → per-asset timeout default is 30s; tune in `scripts/download_assets.py`
- **Noisy color palette** → tune `k` in `scripts/analyze_dna.py:extract_colors`; see `references/dna_extraction.md` § "Colors"
- **Resume needed** → `--resume` reads `manifest.partial.json` and skips completed pages

## Hard rules (never violate)

1. Never write credentials to any file other than the gitignored `.dna-website.env`.
2. Strip auth tokens, cookies, and PII from all saved network logs before they hit disk. See `scripts/utils.py:sanitize_network_log`.
3. Respect `robots.txt` unless `--ignore-robots` is set AND the user confirms.
4. Never auto-deploy or re-publish captured content. This tool produces reference material only.
5. Rate-limit by default. Never burst-request a site.
