# Rebrand workflow

> How to go from a completed DNA-website run to a rebranded reference package.

---

## What the rebrand layer is, and isn't

**It is:**
- A templated version of the extracted design tokens and content, with every brand-specific value replaced by a placeholder
- A swap-map (`swap-map.json`) that maps original strings to placeholders
- A starting point for a developer or designer to use as the spec for rebuilding the site with their own brand

**It is not:**
- A deployable site
- A code generator
- A way to take someone else's site and republish it with your branding (legally fraught and against this tool's terms)

The rebrand workflow assumes the user has permission to inspect the source site and is rebuilding the *design* — not republishing the implementation.

---

## File layout (after build_rebrand.py runs)

```
rebrand/
├── tokens.original.json     # Verbatim copy of analysis/design-tokens.json
├── tokens.template.json     # Same shape, with placeholders
├── content.original.json    # Verbatim copy of analysis/content-inventory.json
├── content.template.json    # Same shape, with placeholders
├── swap-map.json            # original_string → {PLACEHOLDER}
└── README.md                # Instructions (rendered from templates/rebrand_readme.md.j2)
```

---

## Placeholder naming

### Token placeholders

Stable names, easy to grep:

| Original | Placeholder |
|---|---|
| Brand primary color | `{{BRAND_PRIMARY}}` |
| Brand secondary color | `{{BRAND_SECONDARY}}` |
| Success accent | `{{ACCENT_SUCCESS}}` |
| Warning accent | `{{ACCENT_WARNING}}` |
| Danger accent | `{{ACCENT_DANGER}}` |
| Info accent | `{{ACCENT_INFO}}` |
| Body font family | `{{FONT_BODY}}` |
| Heading font family | `{{FONT_HEADING}}` |

Neutrals, spacing, radius, shadow, and motion tokens are **not** replaced — they're usually structural rather than brand-specific. If you want a different spacing scale or radius set, edit `tokens.original.json` directly and skip the template layer.

### Content placeholders

Encoded with the page slug and section index so they're stable and recoverable:

```
{{PAGE_<SLUG>_TITLE}}
{{PAGE_<SLUG>_DESCRIPTION}}
{{PAGE_<SLUG>_SECTION_<i>_HEADING}}
{{PAGE_<SLUG>_SECTION_<i>_PARA_<j>}}
{{PAGE_<SLUG>_SECTION_<i>_CTA_<j>}}
```

The slug is uppercased and non-alphanumerics become underscores: `blog/post-1` → `BLOG__POST_1`.

This naming is deterministic — re-running the rebrand stage produces the same placeholders. That matters because downstream rebuild scripts can be stable across re-runs.

---

## The "round-trip" property

For any captured site, the following must hold:

```
apply_swap(original_content, swap_map) == template_content
apply_swap(template_content, reverse_swap_map) == original_content
```

This is tested in `tests/test_build_rebrand.py`. If the round-trip ever breaks, treat it as a P0 — downstream rebuild scripts depend on this invariant.

Edge case: if two different content strings on different pages happen to collide (e.g., two pages both have heading "Welcome"), the swap map maps both to different placeholders but a plain string replacement on the original HTML would clobber both with the same value. Mitigation: the rebuild script must operate on the structured `content.original.json`, not on raw HTML. The structured JSON has stable paths that can't collide.

---

## The recommended rebuild workflow

Step-by-step, for a developer using this tool's output to build a rebranded version:

### 1. Pick your brand values

Decide:
- Two brand colors (primary, secondary)
- A heading font and a body font (or one font for both)
- Optionally: accent colors (success/warning/danger/info)

If the original had subtle gradient effects or shadow tints derived from the brand color, plan to derive yours similarly (e.g., shadow color = `rgba(<primary_rgb>, 0.1)`).

### 2. Edit `tokens.template.json`

Replace every `{{PLACEHOLDER}}` with your value. Save as `tokens.mybrand.json`.

### 3. Write your copy

Open `content.template.json`. For every placeholder under `pages.*.sections.*`, replace the placeholder with your real copy.

Tip: don't translate verbatim. The original content is a *structural reference* — it tells you where headlines, body copy, and CTAs sit, but the words should be yours. Plagiarizing copy is a separate problem from cloning design.

Save as `content.mybrand.json`.

### 4. Pick your rebuild target

Three rough paths:

**Path A: Static HTML mirror.** Use the captured HTML from `raw/pages/<slug>/rendered.html`, run the swap map over it, get a static site. Good for: visual reference, low-fidelity rebuild, throwaway prototypes. Bad for: production. The captured HTML may contain framework-specific class names and inline scripts you don't want to ship.

**Path B: Component reimplementation.** Use `analysis/component-patterns.json` as the spec for the components you need to build. Use `analysis/design-tokens.json` (or your edited version) as the design-system source. Use `content.mybrand.json` as the content layer. Bind them through your framework of choice (React/Vue/Svelte/Astro). Good for: production sites where you want clean code.

**Path C: Headless reskin.** Pull the captured HTML structure but route all content through a CMS pointed at `content.mybrand.json`. Useful when the original site's IA is exactly what you want but the content is changing frequently.

### 5. Apply the swap map (if doing Path A)

A starter script in Python:

```python
#!/usr/bin/env python3
"""Rebrand: apply swap map to captured HTML, output mirror."""
import json
import re
from pathlib import Path

run_dir = Path("dna-output/example-2026-05-11")
brand_tokens = json.loads(Path("tokens.mybrand.json").read_text())
brand_content = json.loads(Path("content.mybrand.json").read_text())
swap = json.loads((run_dir / "rebrand/swap-map.json").read_text())

# Build forward: original_string -> your_value
forward = {}
for original, placeholder in swap["tokens"].items():
    forward[original] = _resolve_token_placeholder(placeholder, brand_tokens)
for original, placeholder in swap["copy"].items():
    forward[original] = _resolve_copy_placeholder(placeholder, brand_content)

# Sort by length descending so longer strings replace first (avoids
# matching shorter substrings of longer originals).
ordered = sorted(forward.items(), key=lambda kv: -len(kv[0]))

out_dir = Path("dist")
out_dir.mkdir(exist_ok=True)
for page_dir in (run_dir / "raw/pages").iterdir():
    html = (page_dir / "rendered.html").read_text()
    for original, new in ordered:
        html = html.replace(original, new)
    (out_dir / f"{page_dir.name}.html").write_text(html)
```

`_resolve_token_placeholder` and `_resolve_copy_placeholder` walk the brand JSON to find the value for a given placeholder. Implementations are straightforward dict lookups.

### 6. Verify

```bash
python -m scripts.serve dist/    # Won't quite work — serves "inspector" structure
# Instead, use a generic static server:
python3 -m http.server -d dist/
```

Open in a browser. Click through every page. Look for:
- Broken images (asset paths weren't updated for your new domain)
- Untranslated strings (you missed a placeholder)
- Visual artifacts where colors didn't fully swap (CSS-in-JS sometimes embeds colors in style attributes — these get caught by the swap map only if `analyze_dna` saw them)

---

## What about images and fonts?

These are NOT swapped by the rebrand layer. You need to:

1. **Fonts**: source equivalent weights of your chosen font (Google Fonts, Adobe Fonts, self-host). Reference them in `tokens.mybrand.json` under `typography.families`.
2. **Logos and brand imagery**: replace manually in your rebuild. `analysis/icon-library.json` lists inline SVGs that may include brand marks — those are easy to spot.
3. **Photography**: also replace manually. The captured photography is for visual reference, not reuse.

A good practice: after a crawl, immediately move `raw/assets/images/` to `raw/assets/images-original/` and create an empty `raw/assets/images/` that you'll fill with your replacements as you go.

---

## Things people get wrong

1. **Treating the captured HTML as production-ready.** It isn't. It's a reference. Always rebuild.
2. **Reusing brand assets unchanged.** Even fonts you license, you should re-license; even images you like, you should re-source.
3. **Copying copy verbatim.** Plagiarism is a fast way to get your launch noticed (badly).
4. **Skipping the swap map.** It looks tedious but it's what makes the rebrand stable across re-runs.
5. **Editing `original.json` files.** Those are read-only references. Edit the `.template.json` versions.

---

## Future: programmatic rebuild

A future version of this tool may include a `scripts/rebuild.py` that drives the swap → rebuild flow end-to-end, given a brand spec. Not in v0.1.0 — too easy to misuse. v0.1.0 deliberately requires the developer to do the rebuild themselves, which forces them to make decisions about what they're actually cloning.
