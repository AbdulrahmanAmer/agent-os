# Architecture

This document describes the full pipeline, the data flow between stages, and the contracts each stage produces. Read this first when implementing or modifying any module.

## Pipeline overview

The tool runs as 8 sequential stages. Each stage reads from disk (output of the previous stage) and writes to disk (input for the next). This makes the pipeline resumable and debuggable — every intermediate artifact is on disk.

```
[CLI args]
    │
    ▼
┌─────────────────┐
│ 1. Preflight    │  scripts/preflight.py
│                 │  - validates URL
│                 │  - checks blocked-domain list
│                 │  - fetches robots.txt
│                 │  - asks user for confirmation if needed
└────────┬────────┘
         │ writes: output/preflight.json
         ▼
┌─────────────────┐
│ 2. Auth         │  scripts/auth.py  (optional, only if --auth)
│                 │  - drives Chrome MCP through login
│                 │  - handles 2FA via pause-and-prompt
│                 │  - exports cookies + localStorage + sessionStorage
└────────┬────────┘
         │ writes: output/.session/storage_state.json
         ▼
┌─────────────────┐
│ 3. Discover     │  scripts/discover.py
│                 │  - reads sitemap.xml + nested sitemaps
│                 │  - parses robots.txt
│                 │  - BFS crawl from homepage
│                 │  - SPA route sniff via pushState hook
└────────┬────────┘
         │ writes: output/routes.json
         ▼
┌─────────────────┐
│ 4. Crawl        │  scripts/crawl.py
│                 │  - opens each route in Playwright
│                 │  - captures source.html + rendered.html
│                 │  - takes desktop + mobile screenshots
│                 │  - extracts computed styles (injected JS)
│                 │  - logs network traffic
│                 │  - saves a11y tree + metadata
└────────┬────────┘
         │ writes: output/raw/pages/<slug>/*
         │         output/captures.json (manifest of captures)
         ▼
┌─────────────────┐
│ 5. Download     │  scripts/download_assets.py
│    Assets       │  - collects all asset URLs from rendered pages
│                 │  - resolves relative URLs
│                 │  - async download with rate limit + dedupe
│                 │  - hashes content for filenames
└────────┬────────┘
         │ writes: output/raw/assets/<type>/<sha>.<ext>
         │         output/asset_manifest.json (url → local path)
         ▼
┌─────────────────┐
│ 6. Analyze DNA  │  scripts/analyze_dna.py
│                 │  - clusters colors via LAB k-means
│                 │  - derives typography scale
│                 │  - identifies spacing system
│                 │  - extracts radii/shadows/motion
│                 │  - detects repeated component patterns
└────────┬────────┘
         │ writes: output/analysis/design-tokens.json
         │         output/analysis/{color,typography,...}-system.json
         │         output/analysis/component-patterns.json
         ▼
┌─────────────────┐
│ 7. Analyze      │  scripts/analyze_content.py
│    Content      │  - extracts copy grouped by page/section
│                 │  - builds IA tree
│                 │  - inventories images with alt text
└────────┬────────┘
         │ writes: output/analysis/content-inventory.json
         │         output/analysis/information-architecture.json
         ▼
┌─────────────────┐
│ 8. Rebrand      │  scripts/build_rebrand.py
│    + Report     │  - generates token templates with placeholders
│                 │  - generates content templates with placeholders
│                 │  - builds swap-map for find/replace rebuilds
│                 │  scripts/report.py
│                 │  - renders REPORT.md from templates
│                 │  - copies inspector files into place
└────────┬────────┘
         │ writes: output/rebrand/*
         │         output/REPORT.md
         │         output/inspector/*
         │         output/manifest.json (final)
         ▼
       Done
```

## Data flow contracts

Each stage produces specific artifacts that downstream stages depend on. **Do not** change these schemas without updating every consumer. All schemas are formally defined as Pydantic models in `scripts/models.py` and documented in `references/data_contracts.md`.

| Stage | Produces | Schema model |
|---|---|---|
| Preflight | `preflight.json` | `PreflightResult` |
| Auth | `.session/storage_state.json` | Playwright native format |
| Discover | `routes.json` | `RouteList` |
| Crawl | `captures.json` + per-page dirs | `CaptureManifest` + `PageCapture` |
| Assets | `asset_manifest.json` | `AssetManifest` |
| Analyze DNA | `design-tokens.json` + system files | `DesignTokens`, etc. |
| Analyze Content | `content-inventory.json` | `ContentInventory` |
| Rebrand | `tokens.template.json`, etc. | Same as analyze, with placeholders |
| Report | `REPORT.md`, `manifest.json` | `RunManifest` (final, ties everything) |

## Concurrency model

- **Discovery** is async I/O (sitemap fetches, HTML fetches). Concurrency cap: 5.
- **Crawl** is process-bound by Playwright. Concurrency: 3 browser contexts (configurable via `--concurrency`).
- **Asset download** is async I/O. Concurrency cap: 10. Rate limit: 2 req/sec by default with jitter.
- **Analysis** is CPU-bound (k-means, parsing). Single-threaded with `multiprocessing.Pool` for parallel page processing.

## Error handling philosophy

- **Hard fail** on: preflight rejection, auth verify failure, no routes discovered.
- **Soft fail** on: individual page capture errors (log, mark failed in manifest, continue).
- **Soft fail** on: individual asset download errors (log, broken link in inspector, continue).
- **Skip + warn** on: assets > `--max-asset-size`.
- **Retry with backoff** on: 429, 503, timeouts. Use `tenacity` with exponential backoff.

Every soft failure increments a counter that's surfaced in `REPORT.md`.

## Resume semantics

When `--resume` is passed:
1. Look for `output/manifest.partial.json` in the most recent output directory for the target domain.
2. Load completed page slugs.
3. Skip those during stages 4 and 5.
4. Stages 6, 7, 8 always re-run (they're cheap and depend on the full set of captures).

The partial manifest is written incrementally during stage 4 after each page completes successfully.

## Filesystem layout (final)

```
dna-output/<domain>-<YYYYMMDD-HHMMSS>/
│
├── REPORT.md
├── manifest.json
├── manifest.partial.json          # only present if crawl was interrupted
├── preflight.json
├── routes.json
├── captures.json
├── asset_manifest.json
├── run.log                        # full structured log
│
├── .session/
│   └── storage_state.json
│
├── raw/
│   ├── pages/<slug>/
│   │   ├── url.txt
│   │   ├── source.html
│   │   ├── rendered.html
│   │   ├── screenshot.desktop.png
│   │   ├── screenshot.mobile.png  # if --mobile-also
│   │   ├── computed-styles.json
│   │   ├── dom-tree.json
│   │   ├── a11y-tree.json
│   │   ├── network-log.json
│   │   └── meta.json
│   └── assets/{images,fonts,icons,videos,stylesheets,scripts}/
│
├── analysis/
│   ├── design-tokens.json
│   ├── design-tokens.css
│   ├── color-palette.json
│   ├── typography-system.json
│   ├── spacing-system.json
│   ├── radius-system.json
│   ├── shadow-system.json
│   ├── motion-system.json
│   ├── breakpoints.json
│   ├── component-patterns.json
│   ├── information-architecture.json
│   ├── content-inventory.json
│   └── icon-library.json
│
├── rebrand/
│   ├── tokens.original.json
│   ├── tokens.template.json
│   ├── content.original.json
│   ├── content.template.json
│   ├── swap-map.json
│   └── README.md
│
└── inspector/
    ├── index.html
    ├── server.mjs                  # symlink or copy of node_helpers/inspector_server.mjs
    ├── pages/<slug>.html           # rewritten with local asset paths
    ├── assets/                     # symlinks into raw/assets/
    └── tokens-overlay.html
```

## Key cross-stage decisions

### URL → slug conversion
Used by every stage that needs a directory name. Defined in `scripts/utils.py:url_to_slug`.

```
https://example.com/           →  home
https://example.com/about      →  about
https://example.com/blog/post-1 →  blog__post-1
https://example.com/?q=foo     →  home__q-foo
```

Rules: drop scheme + host, replace `/` with `__`, lowercase, replace non-`[a-z0-9_-]` with `-`, collapse `--` to `-`, fallback to `home` for empty.

### Asset hashing
SHA-256 of file content, first 16 hex chars. Defined in `scripts/utils.py:content_hash`. Extension preserved from URL (or sniffed from `Content-Type`).

### Network log sanitization
Strip these headers and JSON fields before writing to disk:
- Headers: `authorization`, `cookie`, `set-cookie`, `x-api-key`, `x-auth-token`, `x-csrf-token`, `proxy-authorization`
- JSON fields (recursive): `password`, `passwd`, `secret`, `token`, `access_token`, `refresh_token`, `api_key`, `apikey`, `private_key`, `client_secret`, `session`, `auth`, anything matching `/^(eyJ|sk_|pk_live_)/` (JWT and Stripe key prefixes)
- Query parameters: `token`, `access_token`, `api_key`, `key`, `secret`

Defined in `scripts/utils.py:sanitize_network_log`. Test coverage required.

## Cap semantics: 0 = unlimited (full-capture mode)

`--max-pages 0` and `--depth 0` are treated as "no cap" by every stage that
would otherwise apply one. Use these for true full-capture runs against
authenticated sites where the page count is unknown in advance. Internally:

- `scripts/discover.py:_bfs_crawl` interprets 0 as `float('inf')` for both
  the page count and the depth limit. The BFS frontier runs to convergence.
- `scripts/discover.py:find_routes` does not slice the route list when
  `max_pages <= 0`.
- `scripts/download_assets.py` has no asset-count cap — it processes every
  collected asset URL. The per-asset size cap (`--max-asset-size`) still
  applies as a sanity check.

For full-capture runs the conservative defaults are:
- `--rate-limit 1` (one request per second) — lower than the standard 2
- `--concurrency 2` — modest parallelism so the request pattern stays human
- `--resume` works against `manifest.partial.json`, written after every page

## Performance budget

Reference targets for a 50-page authenticated site:
- Total wall-clock: < 8 minutes
- Crawl stage: ~3 minutes (50 pages × ~3s + parallelism)
- Asset stage: ~2 minutes (depends heavily on asset count)
- Analysis stages: < 1 minute
- Output size: < 200 MB

If you blow past these substantially, profile before optimizing — usually the culprit is per-page wait timeouts, not algorithmic.
