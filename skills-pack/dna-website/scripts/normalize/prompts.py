"""
Prompt templates for the AI-powered normalizer stages.

Design principles:
  * Every prompt asks for a structured JSON response with an explicit
    schema so downstream stages can validate.
  * Each prompt instructs the model to be CONSERVATIVE — preserve what's
    captured, don't invent new content, don't add features the original
    didn't have.
  * The shared "design DNA" + "content inventory" context is loaded once
    via prompt caching so per-page calls are cheap.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Shared context — built once, cached on the LLM client.
# ---------------------------------------------------------------------------

SHARED_SYSTEM_BASE = """\
You are the dna-website Normalizer. Your job is to convert an SPA capture
of a website into a CLEAN, STATIC, BROWSER-VIEWABLE HTML/CSS/JS project
that opens directly from disk (no Angular runtime, no Webpack manifest,
no API server).

Hard rules you must follow:

1. Preserve the captured INTENT. Do not invent content the original site
   didn't have. Do not change copy. If the original button text was
   "Build Your Own List", keep it exactly. If the original had a
   placeholder like /null in an href, mark it as a dead-link TODO; never
   silently substitute a URL.

2. Strip SPA wrappers. Angular custom elements like <app-root>,
   <app-layout>, <app-page> are noise — replace them with semantic
   HTML5 (<main>, <section>, <header>, <footer>, <nav>, <article>).

3. Replace SPA interactivity with vanilla JS modules. Never reference
   /assets/runtime-*.js, /assets/polyfills-*.js, or any Angular bundle.

4. Use the design tokens from the project's design-tokens.json.
   Reference them as CSS custom properties: var(--color-brand-primary),
   var(--font-size-lg), etc. Don't hardcode hex colors that match a
   token.

5. Never include credentials, API keys, JWT-shaped strings, Stripe-shaped
   keys, or any value that looks like a secret. If you see one in the
   input, replace it with the literal string [REDACTED].

6. Never wire up purchase actions automatically. If a button text matches
   buy / purchase / checkout / pay / subscribe / upgrade / add credits /
   submit payment / confirm purchase, leave it as a no-op with a comment
   `// TODO(operator): wire up <button-name> manually`. We never auto-bind
   purchase handlers.

7. Forms: convert <form action> values to either
   `data-form="<original-action>"` (recorded as TODO) or a generic
   `mailto:` fallback if the form looks like a contact form. Never
   re-target a form to a third-party service on the user's behalf.

8. Return JSON exactly matching the schema in the user prompt. No
   markdown fencing, no commentary outside the JSON object.
"""


def shared_context_blocks(
    design_tokens: dict[str, Any],
    design_blueprint: dict[str, Any] | None,
    interactive_map_aggregate: dict[str, Any] | None,
    content_inventory_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build the cacheable shared system blocks.

    Each block becomes a content block in the system parameter; the LLM
    client marks them with cache_control=ephemeral so per-page calls pay
    only the page-specific delta in tokens.
    """
    blocks: list[dict[str, Any]] = []
    blocks.append({"type": "text", "text": SHARED_SYSTEM_BASE})

    if design_tokens:
        # Keep this trimmed — full design-tokens.json can be very large.
        slim = {
            "color": design_tokens.get("color"),
            "typography": {
                "families": (design_tokens.get("typography") or {}).get("families"),
                "scale": (design_tokens.get("typography") or {}).get("scale"),
                "weights": (design_tokens.get("typography") or {}).get("weights"),
            },
            "spacing": (design_tokens.get("spacing") or {}).get("scale"),
            "radius": (design_tokens.get("radius") or {}).get("scale"),
            "shadow": (design_tokens.get("shadow") or {}).get("scale"),
        }
        import json
        blocks.append({"type": "text",
                       "text": f"DESIGN TOKENS (use these as CSS custom properties):\n{json.dumps(slim, indent=2)}"})

    if design_blueprint:
        import json
        blocks.append({"type": "text",
                       "text": f"NORMALIZED DESIGN BLUEPRINT:\n{json.dumps(design_blueprint, indent=2)}"})

    if interactive_map_aggregate:
        import json
        blocks.append({"type": "text",
                       "text": f"INTERACTIVE-MAP AGGREGATE (whole-site):\n{json.dumps(interactive_map_aggregate, indent=2)}"})

    if content_inventory_summary:
        import json
        blocks.append({"type": "text",
                       "text": f"CONTENT INVENTORY SUMMARY:\n{json.dumps(content_inventory_summary, indent=2)}"})

    return blocks


# ---------------------------------------------------------------------------
# Per-page prompts
# ---------------------------------------------------------------------------

GENERATE_PAGE_HTML_INSTRUCTIONS = """\
You will rewrite ONE page of the captured site into clean, semantic
HTML5. The page is currently an SPA snapshot full of Angular custom
elements.

Inputs you'll receive in the user prompt:
  - The original rendered HTML (post-JS DOM)
  - The page's interactive-map entry (links / buttons / forms / iframes)
  - Per-page content sections (headings, paragraphs, images, CTAs)
  - The page's compact computed-style stats (so you know what fonts /
    spacings / radii the page actually uses)

Your job:
  1. Produce a clean <main> body that mirrors the visible structure of
     the captured page. Use <section> for top-level groups, <h1>/<h2>/<h3>
     for headings, <p> for paragraphs, <ul>/<ol> for lists, <figure> +
     <figcaption> for images with captions, <button> for buttons,
     <a href="..."> for links.
  2. Preserve every link, button, and image. Use the captured src/alt as
     given (already sanitized).
  3. Convert SPA wrappers <app-*> into semantic elements OR remove them
     when they have no semantic meaning.
  4. Add helpful class names that name the component the section
     represents: hero, features, pricing, testimonial-grid, footer-cta,
     etc. These map to component CSS produced elsewhere.
  5. Reference shared CSS as: <link rel="stylesheet" href="assets/css/tokens.css">
     <link rel="stylesheet" href="assets/css/reset.css">
     <link rel="stylesheet" href="assets/css/base.css">
     <link rel="stylesheet" href="assets/css/components.css">
     <link rel="stylesheet" href="assets/css/pages/<slug>.css">
  6. Reference shared JS as: <script src="assets/js/runtime.js" defer></script>
     and only add a per-page <script src="assets/js/pages/<slug>.js" defer></script>
     when you ALSO emit per-page JS.
  7. Form actions: replace any <form action="..."> with
     <form data-original-action="..." onsubmit="return false">.
     Never auto-rewire a form.
  8. Purchase-action buttons (Buy / Subscribe / Upgrade / etc.): leave them
     in the HTML but add data-todo="needs-operator-wiring" so the runtime
     can highlight them.

Return JSON exactly:
{
  "html": "<full HTML5 document>",
  "page_css": "<CSS for THIS PAGE only, scoped to a body[data-page='<slug>'] selector — empty string OK>",
  "page_js": "<JS for THIS PAGE only, empty string OK>",
  "notes": ["one-line notes about choices the operator should review"],
  "todos": ["one-line operator-action items (purchase buttons, form actions, broken links to /null, etc.)"]
}

No markdown fencing. No commentary outside the JSON.
"""


WIRE_INTERACTIONS_INSTRUCTIONS = """\
You will produce a SINGLE shared runtime.js (vanilla JavaScript, no
framework) that wires up the interaction patterns the captured site uses.

Inputs you'll receive in the user prompt:
  - The site-wide interactive-map (every route's buttons / forms /
    iframes / accordions / tabs)
  - A list of slugs (HTML page paths)
  - Existing accordion / tab / modal markup conventions you should
    target via querySelector

Your job:
  1. Write runtime.js as ES2017 module-free (works when loaded with
     <script defer>). Wrap in an IIFE.
  2. Handle these patterns (only if they actually appear in the inputs):
       - Hamburger / mobile menu toggle (.menu-toggle, [aria-controls])
       - <details><summary> accordions (HTML-native; no JS needed but
         emit a smooth-scroll-to-summary helper)
       - Tab panels via [role="tab"] + [role="tabpanel"]
       - Modal triggers via [data-modal="X"] -> <dialog id="X">
       - Cookie banner dismiss (.cookie-banner [data-dismiss])
       - Sticky header on scroll (add .scrolled class to <header>)
  3. NEVER wire purchase / submit-payment / checkout buttons. Detect
     them via data-todo="needs-operator-wiring" and log a console.warn
     when clicked.
  4. NEVER submit forms automatically. Forms with data-original-action
     should preventDefault() and console.warn the original action.
  5. Output should be < 300 lines, dependency-free, no inline templates.

Return JSON exactly:
{
  "js": "<the vanilla JS, including the IIFE wrapper>",
  "css": "<any small CSS needed to support the interactions (e.g. .menu-open class) — empty string OK>",
  "patterns_wired": ["list of pattern names this runtime supports"],
  "patterns_skipped_by_policy": ["list of patterns skipped because they're purchase-related or unsafe"],
  "notes": ["any caveats"]
}

No markdown fencing. No commentary outside the JSON.
"""


CONSOLIDATE_CSS_INSTRUCTIONS = """\
You will receive a concatenated CSS string (all linked + inline CSS the
captured site used) and the project's design tokens. Produce a CLEAN
base.css that:

  1. Starts with a tiny modern reset (box-sizing border-box, margin/padding
     reset on body/headings, img display block + max-width 100%, html
     scroll-behavior smooth).
  2. Sets the body font to var(--font-body, system-ui), color to
     var(--color-text), background to var(--color-background).
  3. Provides utility classes the generated pages will use:
       .container { max-width: var(--layout-max-width, 1200px); margin: 0 auto; padding-inline: 1rem; }
       .btn (default styled button using tokens)
       .btn-primary, .btn-secondary
       .stack > * + * { margin-block-start: 1rem; }  (Andy Bell-style stack)
       .grid (auto-fit grid utility)
       .visually-hidden (accessibility)
  4. Adds component skeletons (no decoration, just structure) for these
     classes IF they appear in the input: .hero, .features, .pricing,
     .testimonials, .faq, .footer, .header, .nav.
  5. Strips Angular-specific selectors (anything starting with app-,
     mat-, cdk-, ng-, _ng[...]).
  6. Strips any !important rules unless absolutely necessary.

Return JSON exactly:
{
  "css": "<the clean base.css>",
  "kept_selectors": <int — how many selectors made it into the output>,
  "stripped_categories": ["angular", "vendor", "duplicate", ...],
  "notes": ["caveats about what was lost"]
}

No markdown fencing. No commentary outside the JSON.
"""
