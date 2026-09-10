# Sample output — what a real run looks like

> This is a synthetic-but-realistic example showing the full directory and key file contents from a run against a fictional `acme-saas.com` marketing site (8 public pages, no auth). Use this to set expectations before running the tool yourself.

---

## The command

```bash
python -m scripts.run https://acme-saas.com \
    --depth 2 \
    --max-pages 20 \
    --mobile-also \
    --output ./outputs/acme-2026-05-11
```

Wall-clock: 38 seconds. 8 pages captured. 47 assets downloaded (12 deduped).

## The directory

```
outputs/acme-2026-05-11/
│
├── REPORT.md                                  ← human-readable summary
├── manifest.json                              ← run metadata
├── run.log                                    ← full structured log
│
├── raw/
│   ├── routes.json                            ← all discovered URLs
│   ├── captures.json                          ← per-page capture index
│   │
│   ├── pages/
│   │   ├── _index/
│   │   │   ├── source.html
│   │   │   ├── rendered.html
│   │   │   ├── screenshot.desktop.png
│   │   │   ├── screenshot.mobile.png
│   │   │   ├── computed-styles.json
│   │   │   ├── a11y-tree.json
│   │   │   ├── network-log.json
│   │   │   └── meta.json
│   │   ├── about/
│   │   │   └── ...
│   │   ├── pricing/
│   │   ├── features/
│   │   ├── blog/
│   │   ├── blog-introducing-acme/
│   │   ├── blog-how-we-built-this/
│   │   └── contact/
│   │
│   └── assets/
│       ├── manifest.json                      ← every asset with hash + url + status
│       ├── images/
│       │   ├── 7f3a9c2e1d5b8a4f.svg           ← logo
│       │   ├── 2c8e1f4a6b9d3e7c.png           ← hero image
│       │   └── ... (15 more)
│       ├── fonts/
│       │   ├── 4a9b2c7e8f1d5a3b.woff2         ← Inter Regular
│       │   ├── 6c1d9e3f8a4b7c2e.woff2         ← Inter SemiBold
│       │   └── ... (4 more)
│       └── css/
│           ├── 8b2e7d4f1a6c9e5b.css
│           └── ...
│
├── analysis/
│   ├── design-tokens.json                     ← derived design system
│   ├── color-palette.json                     ← with cluster details + LAB centroids
│   ├── typography.json                        ← families, scale, weights
│   ├── component-patterns.json                ← repeated UI structures
│   ├── content-inventory.json                 ← all copy
│   ├── ia-tree.json                           ← site hierarchy
│   └── icons/
│       ├── inline/
│       │   ├── arrow-right.svg
│       │   └── ... (8 more)
│       └── library.json                       ← icon-font detection + analysis
│
├── rebrand/
│   ├── README.md                              ← how to customize
│   ├── tokens.template.json                   ← editable design tokens
│   ├── tokens.css                             ← CSS custom properties
│   ├── swap-map.json                          ← original → placeholder mappings
│   └── component-templates/
│       ├── card.html.j2
│       ├── nav.html.j2
│       └── ...
│
└── inspector/
    ├── index.html                             ← browse all captured pages
    ├── _assets/                               ← rewritten copies for local serving
    └── pages/
        ├── _index.html
        ├── about.html
        └── ...
```

---

## Key file contents

### `REPORT.md` (abbreviated)

```markdown
# acme-saas.com — DNA Report

Crawled 2026-05-11 14:02 UTC. 8 pages, 47 assets, 38 seconds wall-clock.

## Brand color palette

| Token | Hex | LAB | Role |
|---|---|---|---|
| `--brand-primary` | `#3b82f6` | L=58 a=4 b=-58 | Primary CTA, links |
| `--brand-primary-dark` | `#1e40af` | L=37 a=22 b=-69 | Hover state, headings |
| `--accent-success` | `#10b981` | L=67 a=-52 b=20 | Success badges |
| `--neutral-900` | `#111827` | L=14 a=2 b=-9 | Body text |
| `--neutral-600` | `#4b5563` | L=44 a=0 b=-5 | Secondary text |
| `--neutral-100` | `#f3f4f6` | L=96 a=0 b=-1 | Surface background |
| `--surface` | `#ffffff` | L=100 | Page background |

## Typography

- **Body:** Inter, system-ui, sans-serif
- **Display:** same, weight 600+
- **Mono:** none detected
- **Scale ratio:** 1.25 (major third)
- **Sizes:** 12, 14, 16, 18, 20, 24, 30, 36, 48, 60 px
- **Weights:** 400, 500, 600, 700

## Spacing

- **Base unit:** 4px (detected via GCD of 247 spacing values)
- **Scale:** 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96 px
- **Common gaps:** 16 (forms), 24 (sections), 64 (hero margins)

## Layout

- **Breakpoints:** 640 (sm), 768 (md), 1024 (lg), 1280 (xl), 1536 (2xl)
- **Container max-width:** 1280px (desktop), padded 16px on mobile
- **Border radii:** 4, 8, 12, 16, 24 px (5 buckets)
- **Shadows:** 3 distinct elevations
- **Motion:** 150ms / 300ms durations; cubic-bezier(0.4, 0, 0.2, 1)

## Component patterns (top 5 by occurrence)

| Pattern | Role guess | Count | Sample pages |
|---|---|---|---|
| `card-with-icon` | feature card | 12 | /, /features |
| `nav-link` | nav item | 8 | all |
| `pricing-tier` | pricing card | 3 | /pricing |
| `testimonial` | testimonial | 4 | / |
| `cta-block` | call to action | 6 | / /about /pricing /features /blog /contact |

## Pages

[thumbnail grid — see inspector/index.html for interactive version]

| URL | Title | Sections | Words |
|---|---|---|---|
| `/` | Acme — the modern way to X | 6 | 312 |
| `/about` | About Acme | 4 | 487 |
| `/pricing` | Pricing | 5 | 219 |
| /features | Features | 7 | 528 |
| /blog | Blog | 1 | 64 |
| /blog/introducing-acme | Introducing Acme | 1 | 1240 |
| /blog/how-we-built-this | How we built this | 1 | 2156 |
| /contact | Contact | 2 | 84 |

## Files of interest

- `analysis/design-tokens.json` — full design system as JSON
- `rebrand/tokens.css` — drop-in CSS custom properties
- `rebrand/README.md` — how to use the rebrand layer
- `inspector/index.html` — interactive browser

## Caveats

- 1 page (/pricing) used network requests that didn't complete in the capture window — interactive pricing widget. The network log shows two pending requests at capture time.
- 4 fonts referenced via Google Fonts CDN — captured but treated as external dependency (you'll need to license/re-host).
- Component pattern detection found 12 `card-with-icon` instances. The first 3 are saved as `analysis/component-patterns.json[0].examples` for inspection.
```

### `analysis/design-tokens.json` (abbreviated)

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-05-11T14:02:38Z",
  "color": {
    "brand": {
      "primary": "#3b82f6",
      "primary_dark": "#1e40af",
      "primary_light": "#93c5fd"
    },
    "accent": {
      "success": "#10b981",
      "warning": "#f59e0b",
      "danger": "#ef4444"
    },
    "neutral": [
      "#ffffff", "#f9fafb", "#f3f4f6", "#e5e7eb",
      "#d1d5db", "#9ca3af", "#6b7280", "#4b5563",
      "#374151", "#1f2937", "#111827"
    ]
  },
  "typography": {
    "families": {
      "body": "Inter, system-ui, sans-serif",
      "display": "Inter, system-ui, sans-serif",
      "mono": null
    },
    "scale_ratio": 1.25,
    "sizes_px": [12, 14, 16, 18, 20, 24, 30, 36, 48, 60],
    "weights": [400, 500, 600, 700],
    "line_heights": [1.0, 1.25, 1.5, 1.75]
  },
  "spacing": {
    "base_px": 4,
    "scale_px": [4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96]
  },
  "radius": {
    "values_px": [4, 8, 12, 16, 24],
    "default_px": 8
  },
  "shadow": {
    "elevations": [
      { "name": "sm", "value": "0 1px 2px 0 rgb(0 0 0 / 0.05)" },
      { "name": "md", "value": "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)" },
      { "name": "lg", "value": "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)" }
    ]
  },
  "motion": {
    "durations_ms": [150, 300],
    "easings": ["cubic-bezier(0.4, 0, 0.2, 1)"]
  },
  "breakpoints_px": {
    "sm": 640, "md": 768, "lg": 1024, "xl": 1280, "2xl": 1536
  }
}
```

### `rebrand/tokens.css` (abbreviated)

```css
:root {
  /* Brand — replace with your colors */
  --brand-primary: {{BRAND_PRIMARY}};        /* was #3b82f6 */
  --brand-primary-dark: {{BRAND_PRIMARY_DARK}}; /* was #1e40af */
  --brand-primary-light: {{BRAND_PRIMARY_LIGHT}}; /* was #93c5fd */

  /* Accent — usually keep these unless your design system differs */
  --accent-success: {{ACCENT_SUCCESS}};      /* was #10b981 */
  --accent-warning: {{ACCENT_WARNING}};      /* was #f59e0b */
  --accent-danger: {{ACCENT_DANGER}};        /* was #ef4444 */

  /* Neutrals — usually keep */
  --neutral-50: #f9fafb;
  --neutral-100: #f3f4f6;
  /* ... */

  /* Type */
  --font-body: {{FONT_BODY}};                /* was Inter, system-ui, sans-serif */
  --font-display: {{FONT_DISPLAY}};          /* was Inter, system-ui, sans-serif */

  /* Spacing */
  --space-1: 4px;
  --space-2: 8px;
  /* ... */
}
```

### `analysis/component-patterns.json[0]` (one entry)

```json
{
  "id": "card-with-icon",
  "role_guess": "feature card",
  "structural_signature": "div>div[icon]+h3+p+a",
  "occurrence_count": 12,
  "occurrences_per_page": {
    "/": 6,
    "/features": 6
  },
  "examples": [
    {
      "page_slug": "_index",
      "selector_path": "section.features > div.grid > div.card:nth-child(1)",
      "outer_html": "<div class=\"card\">...</div>",
      "computed_styles_summary": {
        "padding": "24px",
        "border_radius": "12px",
        "background": "#ffffff",
        "shadow": "sm"
      }
    }
  ]
}
```

### `manifest.json` (abbreviated)

```json
{
  "schema_version": "1.0",
  "tool_version": "0.1.0",
  "target_url": "https://acme-saas.com",
  "started_at": "2026-05-11T14:02:00Z",
  "completed_at": "2026-05-11T14:02:38Z",
  "duration_seconds": 38.4,
  "config": {
    "depth": 2,
    "max_pages": 20,
    "mobile_also": true,
    "rate_limit_rps": 2,
    "concurrency": 3,
    "auth_profile": null
  },
  "stats": {
    "pages_attempted": 8,
    "pages_ok": 8,
    "pages_failed": 0,
    "assets_attempted": 47,
    "assets_ok": 47,
    "assets_failed": 0,
    "assets_deduped": 12,
    "total_bytes_downloaded": 4128442,
    "color_clusters_found": 23,
    "color_clusters_kept": 11,
    "components_detected": 14
  },
  "files": {
    "report": "REPORT.md",
    "tokens": "analysis/design-tokens.json",
    "captures": "raw/captures.json",
    "assets": "raw/assets/manifest.json",
    "inspector_entry": "inspector/index.html"
  }
}
```

---

## What you do with this

### As a designer rebuilding the site

1. Open `inspector/index.html` in your browser, walk through every page
2. Read `REPORT.md` for the design system overview
3. Copy `rebrand/tokens.css` into your new project
4. Replace placeholder tokens with your brand's values
5. Rebuild HTML/CSS from scratch — the captured HTML is reference, not source

### As an engineer studying patterns

1. `analysis/component-patterns.json` — what UI patterns recur
2. `analysis/ia-tree.json` — how the information is organized
3. `raw/pages/*/network-log.json` — what APIs the site uses (sanitized)
4. `raw/pages/*/a11y-tree.json` — accessibility tree if you're studying their semantics

### As a stakeholder making "should we redesign?" decisions

1. Run the tool against your own site and a competitor
2. Compare REPORT.md side-by-side
3. Use `scripts/compare` to track your own site over time

---

## What this is NOT

- Not a one-click site clone. You won't deploy this output anywhere — see [FAQ § "Why isn't this deployable?"](FAQ.md#why-isnt-the-output-directly-deployable).
- Not a JavaScript reverse-engineering tool. We capture network calls (sanitized) but don't try to reconstruct app logic.
- Not a SEO scraper. Single-snapshot output, not a database of content.
