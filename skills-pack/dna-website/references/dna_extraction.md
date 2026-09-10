# DNA Extraction Algorithms

This document specifies exactly how design tokens are derived from raw captures. Every algorithm here should be implementable from the description alone — if you find yourself making big judgment calls, stop and refer back.

## Inputs

After the crawl + asset stages complete, the analyzer reads:

- `raw/pages/<slug>/computed-styles.json` — flattened list of every element's computed styles
- `raw/pages/<slug>/rendered.html` — for structural pattern detection
- `raw/assets/stylesheets/*.css` — for at-rules (media queries, keyframes, font-face)
- `raw/assets/fonts/*` — for font metadata
- `raw/assets/images/*` — for dominant-color extraction on backgrounds

## Output

A single `design-tokens.json` plus per-subsystem files. The token file follows the [W3C Design Tokens spec](https://design-tokens.github.io/community-group/format/) loosely:

```json
{
  "$schema": "design-tokens.v1",
  "color": { ... },
  "typography": { ... },
  "spacing": { ... },
  "radius": { ... },
  "shadow": { ... },
  "motion": { ... },
  "breakpoint": { ... }
}
```

## 1. Color extraction

### Sources to collect
For each element in `computed-styles.json`, harvest:
- `color`
- `background-color`
- `border-color` (and the four side variants if defined)
- `outline-color`
- `fill` and `stroke` (for SVG)
- Color stops parsed out of `background-image: linear-gradient(...)` and `radial-gradient(...)`

Also harvest from raw CSS files:
- Any `color: <value>` declaration
- Any custom property whose value resolves to a color

Skip `transparent`, `currentColor`, `inherit`, and `initial`.

### Normalization
Convert every color string to RGB tuples, then to LAB color space. Use the `colormath` library or roll a tiny CIE conversion (sRGB → linear RGB → XYZ → LAB with D65 illuminant).

Why LAB: perceptual distance. `#FF0000` and `#FF0001` are visually identical but Euclidean RGB distance treats them as different. K-means in LAB gives clusters that match how a human would group colors.

### Counting and clustering
Build a histogram: `{lab_tuple: count}` where count is the number of element appearances. Element area would be better but is expensive to compute — count is good enough as a proxy.

Run k-means clustering in LAB space:
- Initial k from `[6, 8, 12, 16, 20]`
- For each k, compute silhouette score on a 10% random sample (full computation is slow)
- Pick the k with the highest score
- Each cluster's centroid is converted back to sRGB and rounded to nearest hex

### Cluster classification
For each cluster, compute:
- `frequency` — sum of histogram counts of its members
- `saturation` — LAB chroma (`sqrt(a² + b²)`)
- `lightness` — LAB L
- `members` — list of original colors mapped to this cluster

Classify by these rules (in order, first match wins):

```
if saturation < 5:
    → "neutral"
    bucket by lightness:
      L > 95 → neutrals.0 / 50
      L > 80 → neutrals.100 / 200
      ...
      L < 5  → neutrals.950 / 1000
elif frequency > median_frequency * 2 and saturation > 30:
    → "brand"
    rank by frequency:
      highest → brand.primary
      next    → brand.secondary
elif saturation > 50 and frequency < median_frequency:
    → "accent"
    classify by hue:
      H in [80, 160]   → accent.success (greens)
      H in [40, 80]    → accent.warning (yellows/oranges)
      H in [340, 20]   → accent.danger  (reds)
      H in [200, 260]  → accent.info    (blues)
      else             → accent.other
else:
    → "tertiary"
```

Note: hue here is the standard HSL hue, computed from the sRGB centroid. Some colors will land in "tertiary" and that's fine — surface them in the JSON output but don't promote them to named roles.

### Output: `color-palette.json`
```json
{
  "brand": {
    "primary":   { "value": "#1A56DB", "frequency": 4821 },
    "secondary": { "value": "#9333EA", "frequency": 1204 }
  },
  "neutrals": {
    "0":   { "value": "#FFFFFF" },
    "50":  { "value": "#F9FAFB" },
    "100": { "value": "#F3F4F6" },
    "950": { "value": "#030712" }
  },
  "accent": {
    "success": { "value": "#16A34A" },
    "warning": { "value": "#F59E0B" },
    "danger":  { "value": "#DC2626" }
  },
  "tertiary": [...],
  "raw_clusters": [
    { "centroid": "#1A56DB", "size": 4821, "members": ["#1a56db", "#1B57DC", ...] }
  ]
}
```

### Edge cases
- **Sites with no clear brand color** (all neutrals, e.g. a Times-style news site): only neutrals + tertiary populated. The user will see this and know.
- **Sites with gradients everywhere**: gradient stops dominate the histogram. Consider weighting by the inverse of stop count when collecting.
- **Sites in dark mode**: lightness distribution flips. The classification rules still work — `neutrals.0` will be near-black, `neutrals.950` will be near-white.

## 2. Typography

### Sources
For every text-bearing element in `computed-styles.json` (where `element.text` is non-empty):
- `font-family` (resolve the stack to the first available family)
- `font-size` (always in px after computed-style resolution)
- `font-weight` (numeric)
- `line-height` (resolve to a multiplier where possible)
- `letter-spacing`

### Families
Group by resolved primary family. For each family:
- Compute frequency
- Note all weights observed
- Inspect any matching font files in `raw/assets/fonts/` for metadata (use `node_helpers/font_inspect.mjs`)

Top family by frequency → `typography.families.body`. Second-most by frequency, if it's distinct (different name AND different general category like serif/sans), → `typography.families.heading`. If only one family is in use, that's fine — `body` and `heading` both point to it.

### Type scale
Collect all observed `font-size` values. Sort. Compute pairwise ratios. The most common ratio (within ±2%) is the scale. Common scales:
- 1.067 (minor second)
- 1.125 (major second) — most common in modern sites
- 1.2 (minor third)
- 1.25 (major third)
- 1.333 (perfect fourth)
- 1.414 (augmented fourth)
- 1.5 (perfect fifth)
- 1.618 (golden ratio)

If no clear ratio emerges (within tolerance), output the raw sizes as-is and flag `"scale_ratio": null`.

Anchor the scale at the most frequent size (usually 14, 15, or 16 px) and label it `base`. Then label sizes upward as `lg, xl, 2xl, 3xl, 4xl, ...` and downward as `sm, xs`.

### Output: `typography-system.json`
```json
{
  "families": {
    "heading": { "stack": "Inter, -apple-system, sans-serif", "primary": "Inter" },
    "body":    { "stack": "Inter, -apple-system, sans-serif", "primary": "Inter" }
  },
  "scale": {
    "ratio": 1.125,
    "base_px": 16,
    "sizes": {
      "xs":  { "px": 12, "rem": 0.75 },
      "sm":  { "px": 14, "rem": 0.875 },
      "base":{ "px": 16, "rem": 1.0 },
      "lg":  { "px": 18, "rem": 1.125 },
      "xl":  { "px": 20, "rem": 1.25 },
      "2xl": { "px": 24, "rem": 1.5 },
      "3xl": { "px": 30, "rem": 1.875 },
      "4xl": { "px": 36, "rem": 2.25 }
    }
  },
  "weights": [400, 500, 600, 700],
  "line_heights": {
    "tight":  1.2,
    "normal": 1.5,
    "loose":  1.75
  },
  "letter_spacing": {
    "tight":  "-0.02em",
    "normal": "0",
    "wide":   "0.04em"
  }
}
```

## 3. Spacing system

### Sources
For every element, collect all four `padding-*` and all four `margin-*` values, plus `gap` from flex/grid containers.

### Base unit detection
Compute the GCD of all non-zero values. Common bases:
- 4 (Tailwind default)
- 8 (Material Design, many design systems)
- 16 (older / coarser)

If the GCD is 1 or 2, the site probably has inconsistent spacing — emit a warning and fall back to base 4.

### Scale construction
Build a scale: `{ unit_index: pixel_value }` covering observed values.

```
base = 4
scale = {
  0: 0,
  1: 4,    # base × 1
  2: 8,    # base × 2
  3: 12,   # base × 3
  4: 16,
  5: 20,
  6: 24,
  8: 32,
  10: 40,
  12: 48,
  16: 64,
  20: 80,
  24: 96,
  ...
}
```

Only include scale entries that were actually observed at least N times (default N=3).

### Output: `spacing-system.json`
```json
{
  "base_unit_px": 4,
  "scale": {
    "0":  { "px": 0,  "rem": 0 },
    "1":  { "px": 4,  "rem": 0.25 },
    "2":  { "px": 8,  "rem": 0.5 },
    "...": "..."
  },
  "raw_values": [0, 4, 8, 12, 16, 20, 24, 32, 40, 48]
}
```

## 4. Radii

### Sources
Every `border-radius` and per-corner variants.

### Processing
- Strip units (assume px after computed resolution)
- Drop `0` values from the scale (but record the count — most elements will have 0)
- Cluster: round values to nearest integer, then bucket
- Common scales: `[2, 4, 6, 8, 12, 16, 24, 9999]` where 9999 means "fully rounded"
- Specifically detect "pill" radii: any radius > 50% of the element's height

### Output: `radius-system.json`
```json
{
  "scale": {
    "none": 0,
    "sm":   2,
    "base": 4,
    "md":   6,
    "lg":   8,
    "xl":   12,
    "2xl":  16,
    "full": 9999
  }
}
```

## 5. Shadows

### Sources
Every `box-shadow` value, including multiple shadows comma-separated.

### Processing
- Parse the value string. A shadow component looks like:
  ```
  <x> <y> <blur> [<spread>] <color> [inset]
  ```
- Normalize the color (alpha channels common).
- Treat distinct shadow value strings as distinct shadows initially.
- Cluster shadows by visual similarity: shadows with x/y within 1px, blur within 2px, spread within 1px, and color within ΔE 5 merge into one cluster.
- Within each cluster, pick the most-frequent member as the canonical value.
- Sort by perceived "elevation" (heuristic: blur + |spread| + y-offset).

### Output: `shadow-system.json`
```json
{
  "scale": {
    "none": "none",
    "xs":   "0 1px 2px 0 rgba(0,0,0,0.05)",
    "sm":   "0 1px 3px 0 rgba(0,0,0,0.1)",
    "base": "0 4px 6px -1px rgba(0,0,0,0.1)",
    "md":   "0 10px 15px -3px rgba(0,0,0,0.1)",
    "lg":   "0 20px 25px -5px rgba(0,0,0,0.1)",
    "xl":   "0 25px 50px -12px rgba(0,0,0,0.25)"
  },
  "inner": {
    "sm":   "inset 0 1px 2px 0 rgba(0,0,0,0.05)"
  }
}
```

## 6. Motion

### Sources
- `transition` declarations
- `animation` declarations
- `@keyframes` at-rules in CSS files

### Processing for transitions
Parse each `transition` shorthand into `(property, duration, easing, delay)`.
Group by `easing`. Group by `duration`. Identify the canonical durations (most-frequent values).

Common durations to expect: 75ms, 100ms, 150ms, 200ms, 300ms, 500ms, 1000ms.
Common easings: `linear`, `ease`, `ease-in`, `ease-out`, `ease-in-out`, `cubic-bezier(...)`.

### Output: `motion-system.json`
```json
{
  "duration": {
    "instant": "0ms",
    "fast":    "150ms",
    "base":    "200ms",
    "slow":    "300ms",
    "slower":  "500ms"
  },
  "easing": {
    "linear":   "linear",
    "in":       "cubic-bezier(0.4, 0, 1, 1)",
    "out":      "cubic-bezier(0, 0, 0.2, 1)",
    "in-out":   "cubic-bezier(0.4, 0, 0.2, 1)"
  },
  "keyframes": {
    "fade-in":   { "from": "...", "to": "..." },
    "slide-up":  { "from": "...", "to": "..." }
  }
}
```

## 7. Breakpoints

### Sources
All `@media` queries in all captured stylesheets.

### Processing
- Parse each media query, extract `min-width` and `max-width` thresholds
- Deduplicate within ±10px tolerance
- Classify:
  - < 480 → `mobile-sm`
  - 480–767 → `mobile`
  - 768–1023 → `tablet`
  - 1024–1279 → `laptop`
  - 1280–1535 → `desktop`
  - >= 1536 → `wide`

### Output: `breakpoints.json`
```json
{
  "scale": {
    "sm":    "640px",
    "md":    "768px",
    "lg":    "1024px",
    "xl":    "1280px",
    "2xl":   "1536px"
  },
  "raw":     [640, 768, 1024, 1280, 1536]
}
```

## 8. Component pattern detection

This is the hardest part. The goal: identify DOM subtrees that repeat across pages (cards, nav items, buttons, modals, etc.) so the rebuilder knows what reusable components to create.

### Algorithm
For each captured page's `rendered.html`:
1. Parse with BeautifulSoup.
2. For each element with `class` or `role`:
   - Compute a structural signature: a recursive tuple of `(tag, role, class_prefix, child_signatures)` where `class_prefix` is the first two BEM-ish segments of the first class (e.g., `card__body--large` → `card__body`).
   - Limit recursion depth to 3.
3. Hash the signature to get a stable ID.
4. Accumulate: `{signature_hash: [(page_slug, element_path, full_html), ...]}`.

After all pages processed:
- Filter to signatures with `count >= 3` (configurable threshold).
- For each surviving pattern, output:
  - The signature
  - Example occurrences (up to 5)
  - The most common class names used
  - A guess at the component role (header, card, button, etc.) based on tag + role + class hints

### Component-role heuristics
Apply these checks to guess the role:

```
if tag == "button" or class contains "btn" or role == "button":
    role_guess = "button"
elif tag == "nav" or role == "navigation":
    role_guess = "navigation"
elif class contains "card" or class contains "tile":
    role_guess = "card"
elif tag == "header" or role == "banner":
    role_guess = "header"
elif tag == "footer" or role == "contentinfo":
    role_guess = "footer"
elif role == "dialog" or class contains "modal":
    role_guess = "modal"
elif tag == "form":
    role_guess = "form"
elif tag in ("h1","h2","h3"):
    role_guess = "heading"
else:
    role_guess = "unknown"
```

### Output: `component-patterns.json`
```json
{
  "patterns": [
    {
      "id": "p_a1b2c3",
      "role_guess": "card",
      "occurrence_count": 14,
      "signature": ["div", null, "card", [["div", null, "card__media", []], ["div", null, "card__body", [["h3", null, "card__title", []], ["p", null, "card__text", []]]]]],
      "common_classes": ["card", "card--featured", "card--compact"],
      "examples": [
        { "page": "home", "path": "body>main>section:nth(2)>div:nth(0)", "html_snippet": "..." }
      ]
    }
  ]
}
```

## 9. Icon library

### Detection
Icons are either:
- Inline `<svg>` elements (often small, with `viewBox`)
- `<img>` references to SVG files
- Icon font glyphs (`<i class="fa-...">`, `<span class="material-icons">`)
- CSS `background-image: url(some-icon.svg)`

### Extraction
- Collect all inline SVGs from rendered HTML. Hash by normalized SVG content (strip whitespace, sort attributes). Save deduplicated copies to `analysis/icons/<hash>.svg`.
- Index referenced SVG files from `raw/assets/icons/`.
- For icon fonts: list the font + the class names seen. The rebuilder can swap to a different icon font with the same class names.

### Output: `icon-library.json`
```json
{
  "inline_svgs": [
    {
      "hash": "abc123",
      "path": "analysis/icons/abc123.svg",
      "used_on": ["home", "about", "contact"],
      "guessed_name": "menu",
      "viewBox": "0 0 24 24"
    }
  ],
  "icon_fonts": [
    {
      "family": "Material Icons",
      "classes_used": ["menu", "close", "arrow_forward"]
    }
  ]
}
```

Guessed name comes from a hardcoded list of common icon shapes (look for `M3 12h18` patterns to detect "menu", etc.) — or fall back to "icon-1", "icon-2".

## Final assembly

`analyze_dna.py` runs all 9 sub-analyzers in sequence and writes:
- `design-tokens.json` — combined token tree
- `design-tokens.css` — same data as CSS custom properties (rendered from `templates/tokens.css.j2`)
- Each subsystem file individually

## Quality checks

Before declaring success, the analyzer self-checks:

1. **At least one brand color identified** — if not, emit a warning to `REPORT.md`.
2. **At least one font family identified** — if not, abort the analysis stage (capture probably failed).
3. **Spacing GCD ≥ 4** — if not, warn that spacing is inconsistent.
4. **Component patterns count ≥ 5** — if not, the site is unusually unique-per-page or capture was incomplete.

Failures of (1), (3), (4) are warnings. Failure of (2) is a hard error.

## Tuning knobs

All thresholds live as constants at the top of `analyze_dna.py`. Defaults in parentheses.

- `K_CANDIDATES` (`[6, 8, 12, 16, 20]`) — k-means cluster counts to try
- `SILHOUETTE_SAMPLE_FRAC` (`0.1`) — fraction of points for silhouette
- `NEUTRAL_SATURATION_MAX` (`5`) — LAB chroma below which a color is neutral
- `BRAND_FREQ_MULTIPLIER` (`2`) — × median to qualify as brand
- `ACCENT_SATURATION_MIN` (`50`)
- `SHADOW_MERGE_DELTA_E` (`5`)
- `SHADOW_MERGE_BLUR_PX` (`2`)
- `COMPONENT_MIN_OCCURRENCE` (`3`)
- `COMPONENT_RECURSION_DEPTH` (`3`)
- `SPACING_MIN_OCCURRENCE` (`3`)
