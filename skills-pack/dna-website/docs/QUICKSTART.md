# Quickstart — five minutes to your first extraction

Goal: in five minutes, have a real website's design tokens extracted to a local directory you can browse.

## Prerequisites

- Python 3.11+
- Node 20+
- Chrome (for the inspector)
- A public website you have legitimate reason to study (e.g. your own marketing site, a competitor you're researching, a public design reference)

## 1. Install (2 min)

```bash
git clone <this-repo> dna-website
cd dna-website
make install
```

What `make install` does:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
npm install
```

If anything goes wrong, run `python -m scripts.doctor` — it reports each piece of the environment and what's missing.

## 2. Verify (30 sec)

```bash
make smoke
```

Expected:
```
✓ python deps installed
✓ playwright browsers installed
✓ node deps installed
✓ smoke tests passing
✓ doctor: all green
```

## 3. Run against a public site (2 min)

Pick something small. A 5–10 page marketing site is ideal for a first run.

```bash
python -m scripts.run https://example.com \
    --depth 2 \
    --max-pages 10 \
    --output ./my-first-run
```

You'll see progress lines like:

```
[14:02:11] preflight     → OK (example.com)
[14:02:12] discover      → 7 routes found (sitemap=1, links=6)
[14:02:13] crawl 1/7     → / (200, 1.2s, 12 styles, 3 assets queued)
[14:02:14] crawl 2/7     → /about (200, 0.9s, 8 styles, 1 asset queued)
...
[14:02:25] crawl 7/7     → /contact (200, 0.7s)
[14:02:26] assets        → downloading 18 unique (4 deduped)
[14:02:34] analyze_dna   → 4 brand colors, 1 typeface, scale 1.25, base 8px
[14:02:35] analyze_content → 7 pages, 24 sections, 12 CTAs
[14:02:36] build_rebrand → 18 token placeholders, swap-map written
[14:02:37] report        → REPORT.md, inspector built
[14:02:37] done in 26.4s → ./my-first-run/
```

## 4. Look at the output (30 sec)

```bash
ls ./my-first-run/
```

```
my-first-run/
├── REPORT.md                     ← read this first
├── manifest.json                 ← run metadata
├── raw/                          ← fetched HTML + screenshots + assets
├── analysis/                     ← extracted design tokens + content + components
├── rebrand/                      ← templates with placeholders + swap-map
└── inspector/                    ← browser-renderable local mirror
```

Open `REPORT.md`. You'll see:
- Brand color palette with hex codes
- Type system (families, sizes, weights)
- Spacing system (base unit + scale)
- All pages captured, with thumbnails
- Component patterns detected

## 5. Browse interactively (1 min)

```bash
python -m scripts.serve ./my-first-run
```

Opens http://localhost:7777. You'll see:
- A thumbnail grid of every page
- Click a thumbnail → see the rewritten page with assets loaded locally
- Sidebar shows design tokens for that specific page
- Toolbar links to source HTML, rendered HTML, computed styles, network log

Press Ctrl+C in the terminal to stop the server.

---

## What just happened

You ran the full 8-stage pipeline:

1. **Preflight** — confirmed the domain isn't blocked, checked robots.txt
2. **Auth** — no-op (public site)
3. **Discover** — found URLs via sitemap.xml + link following
4. **Crawl** — for each URL: source HTML, rendered HTML, computed styles, screenshots
5. **Assets** — downloaded images, fonts, CSS files (deduped by content hash)
6. **Analyze DNA** — clustered colors in LAB space, detected type scale, derived spacing system
7. **Analyze content** — extracted copy, built site IA tree, found CTAs
8. **Build rebrand + report** — produced the editable token templates and the human-readable REPORT.md

Every intermediate artifact is on disk. Nothing is hidden in a cache.

---

## Next steps

- **Try an authenticated site:** [EXAMPLES.md § Recipe 2](EXAMPLES.md#recipe-2--authenticated-dashboard-saas-your-team-uses)
- **Understand the output:** [SAMPLE_OUTPUT.md](SAMPLE_OUTPUT.md)
- **Tune for your site:** [references/calibration.md](../references/calibration.md)
- **Read the design rationale:** [FAQ.md](FAQ.md)

## Help

- `python -m scripts.run --help` — full CLI reference
- `python -m scripts.doctor` — diagnose environment issues
- [references/troubleshooting.md](../references/troubleshooting.md) — known failure modes

If the run fails:
1. Check the URL is reachable in your normal browser
2. Run `python -m scripts.doctor` — environment problems show up here
3. Re-run with `--verbose` — you'll see exactly which stage failed and why
4. Search the troubleshooting doc for your error message
