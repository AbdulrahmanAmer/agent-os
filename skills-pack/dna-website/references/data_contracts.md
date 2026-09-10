# Data Contracts

This document is the source of truth for every JSON file the tool reads or writes. Whenever you touch I/O code, check this file first. The formal definitions live in `scripts/models.py` as Pydantic models — this document mirrors them with explanation.

## File-to-model map

| File | Model in `models.py` | Stage that writes |
|---|---|---|
| `preflight.json` | `PreflightResult` | preflight |
| `.session/storage_state.json` | (Playwright native) | auth |
| `routes.json` | `RouteList` | discover |
| `captures.json` | `CaptureManifest` | crawl |
| `raw/pages/<slug>/computed-styles.json` | `ComputedStylesDoc` | crawl |
| `raw/pages/<slug>/network-log.json` | `NetworkLog` | crawl |
| `raw/pages/<slug>/meta.json` | `PageMeta` | crawl |
| `raw/pages/<slug>/dom-tree.json` | `DomTree` | crawl |
| `raw/pages/<slug>/a11y-tree.json` | `A11yTree` | crawl |
| `asset_manifest.json` | `AssetManifest` | download_assets |
| `analysis/design-tokens.json` | `DesignTokens` | analyze_dna |
| `analysis/color-palette.json` | `ColorPalette` | analyze_dna |
| `analysis/typography-system.json` | `TypographySystem` | analyze_dna |
| `analysis/spacing-system.json` | `SpacingSystem` | analyze_dna |
| `analysis/radius-system.json` | `RadiusSystem` | analyze_dna |
| `analysis/shadow-system.json` | `ShadowSystem` | analyze_dna |
| `analysis/motion-system.json` | `MotionSystem` | analyze_dna |
| `analysis/breakpoints.json` | `BreakpointSystem` | analyze_dna |
| `analysis/component-patterns.json` | `ComponentPatterns` | analyze_dna |
| `analysis/icon-library.json` | `IconLibrary` | analyze_dna |
| `analysis/content-inventory.json` | `ContentInventory` | analyze_content |
| `analysis/information-architecture.json` | `IATree` | analyze_content |
| `rebrand/tokens.template.json` | same as `DesignTokens` | build_rebrand |
| `rebrand/content.template.json` | same as `ContentInventory` | build_rebrand |
| `rebrand/swap-map.json` | `SwapMap` | build_rebrand |
| `manifest.json` (final) | `RunManifest` | report |

## Key schemas in detail

### PreflightResult
```typescript
{
  url: string,                     // original input URL
  normalized_url: string,          // after URL parsing/normalization
  domain: string,
  base_origin: string,             // scheme://host
  blocked_category: string | null, // "banking" | "healthcare" | null | ...
  robots_allowed: boolean,
  robots_disallow_paths: string[],
  user_confirmed_override: boolean,
  flags: {
    ignore_robots: boolean,
    i_own_this_site: boolean,
    include_subdomains: boolean
  },
  warnings: string[]
}
```

### RouteList
```typescript
{
  base_origin: string,
  routes: Route[]
}

Route {
  url: string,
  slug: string,                    // url_to_slug(url)
  depth: number,                   // distance from seed in BFS
  source: "sitemap" | "robots-disallow" | "crawl" | "spa-sniff" | "manual",
  auth_required: boolean,
  discovered_at: string            // ISO 8601
}
```

### CaptureManifest
```typescript
{
  total: number,
  successful: number,
  failed: number,
  captures: Capture[]
}

Capture {
  url: string,
  slug: string,
  status: "ok" | "error",
  error_message?: string,
  duration_ms: number,
  http_status: number,
  redirected_to?: string,
  files: {
    source_html: string,           // relative path from output dir
    rendered_html: string,
    screenshot_desktop: string,
    screenshot_mobile?: string,
    computed_styles: string,
    dom_tree: string,
    a11y_tree: string,
    network_log: string,
    meta: string
  },
  viewport: {
    width: number,
    height: number
  }
}
```

### ComputedStylesDoc
```typescript
{
  page_slug: string,
  captured_at: string,
  elements: ElementStyles[]
}

ElementStyles {
  tag: string,                     // lowercase tag name
  classes: string[],
  id?: string,
  role?: string,                   // aria role
  path: string,                    // css-like selector path
  text: string | null,             // inner text if leaf, capped at 200 chars
  styles: {                        // computed values, always strings
    color: string,
    "background-color": string,
    "background-image": string,
    "font-family": string,
    "font-size": string,
    "font-weight": string,
    "line-height": string,
    "letter-spacing": string,
    padding: string,
    margin: string,
    "border-radius": string,
    "box-shadow": string,
    border: string,
    display: string,
    "flex-direction": string,
    "grid-template-columns": string,
    transition: string,
    transform: string,
    opacity: string
    // ... see browser_scripts/extract_computed_styles.js for canonical list
  },
  bbox?: { x: number, y: number, w: number, h: number }   // optional, for component patterns
}
```

### NetworkLog
```typescript
{
  page_slug: string,
  entries: NetworkEntry[]
}

NetworkEntry {
  url: string,
  method: string,                  // GET, POST, ...
  resource_type: string,           // document, xhr, fetch, script, ...
  status: number,
  request_headers: Record<string, string>,    // sanitized
  request_body_shape?: object | null,         // JSON keys only, no values for sensitive ones
  response_headers: Record<string, string>,   // sanitized
  response_body_shape?: object | null,        // for JSON responses, shape only
  response_size: number,
  duration_ms: number,
  initiator?: string
}
```

Note: only the *shape* of JSON request/response bodies is saved, never the full content. This serves API discovery without leaking data. See `scripts/utils.py:extract_json_shape`.

### PageMeta
```typescript
{
  url: string,
  final_url: string,               // after redirects
  title: string,
  description?: string,
  canonical?: string,
  og: Record<string, string>,
  twitter: Record<string, string>,
  json_ld: object[],
  lang?: string,
  viewport?: string,
  favicon?: string,
  manifest_url?: string
}
```

### AssetManifest
```typescript
{
  assets: Asset[],
  by_url: Record<string, string>,   // original url → local path
  stats: {
    total: number,
    by_type: Record<string, number>,
    total_bytes: number,
    failed: number,
    skipped_oversized: number
  }
}

Asset {
  original_url: string,
  local_path: string,               // relative to output dir
  content_hash: string,             // sha256[:16]
  content_type: string,
  size_bytes: number,
  type: "image" | "font" | "icon" | "video" | "stylesheet" | "script",
  used_on_pages: string[],          // slugs
  download_status: "ok" | "failed" | "skipped",
  failure_reason?: string
}
```

### DesignTokens (top-level token tree)
```typescript
{
  $schema: "design-tokens.v1",
  generated_at: string,
  color: ColorTokens,
  typography: TypographyTokens,
  spacing: SpacingTokens,
  radius: RadiusTokens,
  shadow: ShadowTokens,
  motion: MotionTokens,
  breakpoint: BreakpointTokens
}
```

Each sub-tree's shape is documented in `references/dna_extraction.md` and modeled in `scripts/models.py`.

### ContentInventory
```typescript
{
  pages: Record<string /* slug */, PageContent>
}

PageContent {
  url: string,
  title: string,
  description?: string,
  sections: ContentSection[]
}

ContentSection {
  // best-effort detection: <section>, <article>, or fallback to nearest landmark
  id?: string,
  heading?: string,
  level?: number,                  // h1=1, h2=2, ...
  paragraphs: string[],
  links: { text: string, href: string }[],
  images: { src: string, alt: string, caption?: string }[],
  ctas: { text: string, href?: string, kind: "button" | "link" }[]
}
```

### IATree
```typescript
{
  root: IANode
}

IANode {
  slug: string,
  url: string,
  title: string,
  depth: number,
  children: IANode[]
}
```

Built by clustering pages by URL path prefix and depth.

### ComponentPatterns
See `references/dna_extraction.md` § 8 for shape.

### SwapMap
```typescript
{
  // Used to convert original content/tokens to placeholder versions and back.
  // Apply naive find/replace on rendered HTML to get a "rebranded" preview.
  tokens: Record<string /* original */, string /* placeholder */>,
  copy: Record<string /* original */, string /* placeholder */>,
  // example:
  // tokens: { "#1A56DB": "{{BRAND_PRIMARY}}", "Inter": "{{FONT_BODY}}" }
  // copy:   { "Welcome to Acme": "{{PAGE_HOME_HERO_HEADING}}" }
  meta: {
    token_count: number,
    copy_count: number,
    generated_at: string
  }
}
```

### RunManifest (top-level, written last)
```typescript
{
  schema_version: "1.0",
  target_url: string,
  base_origin: string,
  domain: string,
  output_dir: string,
  started_at: string,
  completed_at: string,
  duration_seconds: number,
  flags: object,                   // all CLI flags as parsed
  stats: {
    pages_crawled: number,
    pages_failed: number,
    assets_downloaded: number,
    assets_failed: number,
    total_bytes: number,
    unique_colors: number,
    unique_fonts: number,
    component_patterns_detected: number
  },
  files: {
    report: "REPORT.md",
    routes: "routes.json",
    captures: "captures.json",
    assets: "asset_manifest.json",
    design_tokens: "analysis/design-tokens.json",
    content: "analysis/content-inventory.json",
    ia: "analysis/information-architecture.json",
    inspector_index: "inspector/index.html"
  },
  warnings: string[]
}
```

## Backward compatibility

`schema_version` exists for future-proofing. If you change any contract, bump it and add migration logic in `scripts/models.py:load_manifest`. The current version is `1.0`.

## Validation discipline

Every reader and writer must validate via Pydantic. No raw `json.dump` / `json.load` without a model in between. The reason: contracts get violated silently and the next stage chokes far from the source of the bug. Pydantic raises on contract violations immediately.

Pattern:
```python
from scripts.models import RouteList

def write_routes(path: Path, routes: list[Route]) -> None:
    doc = RouteList(base_origin=..., routes=routes)
    path.write_text(doc.model_dump_json(indent=2))

def read_routes(path: Path) -> RouteList:
    return RouteList.model_validate_json(path.read_text())
```

## Sensitive data in contracts

These fields must always be redacted if they contain anything credential-like (see `scripts/utils.py:sanitize_*`):

- `NetworkEntry.request_headers`
- `NetworkEntry.response_headers`
- `NetworkEntry.request_body_shape`
- `NetworkEntry.response_body_shape`
- `PageMeta` — generally safe, but check for accidental tokens in `og` tags

Never include the following in any contract:
- Raw cookies (they belong in `.session/storage_state.json` only)
- Auth tokens of any kind
- Email recipients, phone numbers, SSNs, or other PII observed in page content
