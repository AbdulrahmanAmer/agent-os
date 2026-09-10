# DNA-website

A skill + tool that captures a website's full "DNA" — every route, every asset, the complete design system, and all content — into a local, inspectable package.

## What it does
- Crawls a target site (public + authenticated)
- Captures rendered HTML, computed styles, screenshots, network traffic, all assets
- Derives a design token system (colors, typography, spacing, radii, shadows, motion)
- Builds a content inventory and rebrand layer (editable tokens + copy templates)
- Spins up a local inspector to browse the cloned site offline

## What it doesn't do
- Auto-deploy or re-publish
- Bypass paywalls, CAPTCHAs, or anti-bot systems
- Clone backends or proprietary APIs

## Quick start

```bash
# 1. Install Python deps
pip install -e .

# 2. Install Playwright browsers
python -m playwright install chromium

# 3. Install Node deps for inspector + CSS tools
npm install

# 4. Copy and fill in the env template
cp .dna-website.env.example .dna-website.env
# edit .dna-website.env to add your login profiles

# 5. Install the skill into Claude
cp -r . ~/.claude/skills/dna-website/

# 6. Trigger from Claude
/dna-website https://example.com
# or with auth
/dna-website https://app.example.com --auth my-profile
```

## Direct CLI usage (without Claude)

```bash
python -m scripts.run https://example.com --depth 3 --max-pages 50
python -m scripts.run https://app.example.com --auth my-profile --mobile-also
python -m scripts.run https://example.com --resume  # continue interrupted crawl
```

## Output

After a successful run you'll find:

```
dna-output/<domain>-<timestamp>/
├── REPORT.md                  # Start here — human-readable summary
├── manifest.json              # Machine-readable index
├── raw/                       # Captured HTML, screenshots, assets
├── analysis/                  # Extracted design tokens, IA, content
├── rebrand/                   # Editable templates with placeholders
└── inspector/                 # Local browseable copy
```

Open the inspector with:
```bash
node node_helpers/inspector_server.mjs dna-output/<domain>-<timestamp>/inspector
# Then open http://localhost:7777
```

## Documentation

- `references/architecture.md` — Full pipeline + data flow
- `references/auth_strategies.md` — Login handling decisions
- `references/dna_extraction.md` — How design tokens are derived
- `references/data_contracts.md` — JSON schemas for every output file
- `references/troubleshooting.md` — Common failure modes

## Hard rules

This tool will refuse to run, or require an explicit override flag, when:
- The target domain is in the blocked-category list (banking, government, healthcare, dating)
- `robots.txt` disallows the path and `--ignore-robots` isn't set
- The target asks for sensitive credentials beyond standard username/password
- The user hasn't confirmed they have legitimate access

This is by design. The tool is for cloning sites you own, sites you have permission to study, or public reference material — not for unauthorized scraping.
