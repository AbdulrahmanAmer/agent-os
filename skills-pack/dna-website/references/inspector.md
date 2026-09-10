# Inspector

> The local, browser-based UI for exploring a completed DNA-website run.

---

## What it is

A local Express server (Node) that serves the contents of a run's `inspector/` directory plus the underlying `raw/` and `analysis/` directories. Run it, open `http://localhost:7777`, click around.

## Launching

```bash
python -m scripts.serve dna-output/example-2026-05-11
```

Or directly:
```bash
node node_helpers/inspector_server.mjs dna-output/example-2026-05-11/inspector
```

Defaults to port 7777. Override with `--port` (Python) or `INSPECTOR_PORT` (Node env).

The Python wrapper opens the URL in your default browser automatically. Pass `--no-open` to skip.

---

## Routes

| Path | Serves |
|---|---|
| `/` | Index page — thumbnail grid of every captured page |
| `/pages/<slug>.html` | Rewritten page HTML, wrapped in inspector chrome |
| `/tokens.css` | The design tokens as CSS custom properties |
| `/manifest.json` | The inspector's own metadata |
| `/raw/*` | Read-only mount of `<run>/raw/` (assets, source HTML, etc.) |
| `/analysis/*` | Read-only mount of `<run>/analysis/` (JSON artifacts) |

---

## What "rewritten page HTML" means

In `raw/pages/<slug>/rendered.html`, every `<img src>`, `<link href>`, `<script src>`, and CSS `url()` still points at the original site's URLs. If you opened that file directly, your browser would try to fetch from the live site (and probably fail because of CORS or auth).

The inspector's prep step (`scripts/report.py:_build_inspector`) walks every page and rewrites these references to point at the local cached copies under `../../raw/assets/`. The result lives at `inspector/pages/<slug>.html`.

Browsing the inspector is what the site looked like at capture time, served entirely from disk, with no network calls.

---

## Inspector chrome

Each page is wrapped in `templates/inspector_page.html.j2`, which adds a top toolbar:

```
← back to index    https://example.com/about    view source · view rendered · styles · network
```

Toolbar links:
- **view source** → original HTML before JS execution
- **view rendered** → final HTML after JS finished
- **styles** → `computed-styles.json` for every element
- **network** → `network-log.json` (already sanitized)

---

## Acceptance criteria (manual)

When the inspector is "working":

- [ ] Index loads in < 1 second
- [ ] Thumbnails render for every captured page
- [ ] Clicking a thumbnail opens that page's rewritten HTML
- [ ] At least one image visibly loads on each page (not broken)
- [ ] Stylesheets render correctly (page looks like the original, modulo any fonts that weren't downloaded)
- [ ] Top toolbar links all open valid JSON or HTML
- [ ] "Back to index" returns to home
- [ ] No browser console errors on any page (other than from the captured site's own JS — its API calls will fail, expected)

---

## Implementation notes

### Why Express and not just a static file server

The static-file part is 80% of the value. We use Express to:
- Mount multiple directories at different paths (`/raw`, `/analysis`)
- Cleanly handle the path traversal protections (`express.static` does this for us)
- Eventually support interactive features (filter, search, diff between runs) without a separate process

### Path rewriting heuristics

`scripts/utils.rewrite_html_asset_paths` handles the rewrite. Rules:

1. Absolute URLs whose host matches a downloaded asset → rewrite to local path.
2. Protocol-relative URLs (`//cdn.example.com/foo.png`) → rewrite same as absolute.
3. Path-relative URLs → resolve against the page's URL, then check the map.
4. `srcset` attributes — split on commas, rewrite each URL.
5. CSS `url()` calls in inline `style` attributes — rewrite.
6. Inline `<style>` blocks — currently NOT rewritten (TODO M10). The inspector handles this by also serving the original stylesheet files which it loads via the rewritten `<link>` tags.
7. `<script src>` URLs are rewritten. This means the page's JS will try to run from the local cache. Most of the time it works; sometimes it fails because the JS makes API calls. The inspector tolerates this.

### Things the inspector deliberately does NOT do

- It does NOT block the page's JS. The page runs as it did during capture. If the captured JS tried to send analytics, those calls will fail (network is local) — that's fine.
- It does NOT serve dynamic data. Form submissions on the cached pages will do nothing useful. This is by design — the inspector is for inspection, not interaction.
- It does NOT compare pages or diff designs. That's a future feature (see `scripts/compare.py` stub).
- It does NOT render the design tokens as a visual swatch board. Use `tokens.css` directly, or a tool like Knapsack / Specify.

---

## Adding inspector features

The inspector code lives in two places:

- `node_helpers/inspector_server.mjs` — the server (small, ~50 lines)
- `templates/inspector_*.html.j2` — the HTML

If you want to add a feature:
- A new server route → edit the Node file
- New UI → edit the Jinja templates
- A new data source → make sure `scripts/report.py:_build_inspector` writes it to disk; the server just serves files

Keep the inspector simple. The pipeline writes static files; the inspector serves them. No build step, no React, no Vite.
