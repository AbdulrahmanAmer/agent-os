"""
AI-powered CSS consolidation.

Input:  real-project/assets/css/raw.css  (concatenated, Angular-stripped)
        real-project/assets/css/tokens.css  (CSS vars)

Output: real-project/assets/css/base.css       (reset + utilities + body defaults)
        real-project/assets/css/components.css (component skeletons)

The AI receives the raw CSS + the design-tokens summary, and emits a
much smaller base + components stylesheet that uses the CSS vars. The
deterministic fallback writes a hand-rolled base.css when the LLM is
unavailable or its output is too big.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .llm import LLMClient
from .prompts import CONSOLIDATE_CSS_INSTRUCTIONS

log = logging.getLogger(__name__)


# Maximum chars of raw.css we feed the LLM. Above this we truncate.
# 20k chars keeps the call inside a 60-90 s wall-clock on the CLI backend.
MAX_RAW_CHARS = 20_000


@dataclass
class ConsolidateStats:
    base_bytes: int = 0
    components_bytes: int = 0
    raw_bytes_in: int = 0
    kept_selectors: int = 0
    notes: list[str] = field(default_factory=list)


FALLBACK_BASE_CSS = r"""
/* base.css — dna-website normalizer deterministic fallback */

*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: var(--font-body, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
  font-size: var(--font-size-base, 1rem);
  line-height: 1.5;
  color: var(--color-text, #11181c);
  background: var(--color-background, #fff);
  -webkit-font-smoothing: antialiased;
}
h1, h2, h3, h4, h5, h6 {
  font-family: var(--font-heading, var(--font-body, system-ui));
  margin-block: 0 0.5em;
  line-height: 1.2;
}
h1 { font-size: var(--font-size-4xl, 2.25rem); }
h2 { font-size: var(--font-size-3xl, 1.875rem); }
h3 { font-size: var(--font-size-2xl, 1.5rem); }
h4 { font-size: var(--font-size-xl, 1.25rem); }
p { margin-block: 0 1em; }
img, picture, video, canvas, svg { display: block; max-width: 100%; height: auto; }
a { color: var(--color-brand-primary, #1a73e8); text-decoration: underline; text-underline-offset: 2px; }
a:hover { text-decoration-thickness: 2px; }
button, input, select, textarea { font: inherit; color: inherit; }
button { cursor: pointer; }

/* layout */
.container {
  width: 100%;
  max-width: var(--layout-max-width, 1200px);
  margin-inline: auto;
  padding-inline: var(--space-4, 1rem);
}
.stack > * + * { margin-block-start: var(--space-4, 1rem); }
.grid { display: grid; gap: var(--space-4, 1rem); }
.flex { display: flex; gap: var(--space-2, 0.5rem); }
.visually-hidden {
  position: absolute !important;
  width: 1px !important; height: 1px !important;
  padding: 0 !important; margin: -1px !important;
  overflow: hidden !important; clip: rect(0,0,0,0) !important;
  white-space: nowrap !important; border: 0 !important;
}

/* buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5em;
  padding: 0.75rem 1.5rem;
  border-radius: var(--radius-base, 4px);
  border: 1px solid transparent;
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease, transform 0.05s ease;
}
.btn:active { transform: translateY(1px); }
.btn-primary {
  background: var(--color-brand-primary, #1a73e8);
  color: #fff;
}
.btn-primary:hover { filter: brightness(0.95); }
.btn-secondary {
  background: transparent;
  color: var(--color-brand-primary, #1a73e8);
  border-color: var(--color-brand-primary, #1a73e8);
}
.btn-secondary:hover { background: color-mix(in srgb, var(--color-brand-primary, #1a73e8) 8%, transparent); }

/* sections */
section, header, footer, main, article, nav { display: block; }
header { padding-block: 1rem; }
footer { padding-block: 2rem; margin-block-start: 3rem; background: var(--color-footer-bg, #1a1a1a); color: #e6e6e6; }
footer a { color: inherit; }

/* image-list grids */
.features, .pricing, .testimonials, .grid {
  display: grid;
  gap: var(--space-6, 1.5rem);
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
}

/* dialog */
dialog {
  border: none;
  border-radius: var(--radius-md, 8px);
  box-shadow: var(--shadow-md, 0 4px 16px rgba(0,0,0,0.18));
  padding: 1.5rem;
  max-width: min(90vw, 480px);
}
dialog::backdrop { background: rgba(0,0,0,0.4); }

/* TODO highlights */
[data-todo="needs-operator-wiring"] {
  position: relative;
}
[data-todo="needs-operator-wiring"]::after {
  content: "TODO";
  position: absolute; top: -8px; right: -8px;
  background: var(--color-accent-warning, #f96138);
  color: #fff;
  font-size: 10px; font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  pointer-events: none;
}
"""


FALLBACK_COMPONENTS_CSS = r"""
/* components.css — dna-website normalizer fallback */

.hero {
  padding-block: clamp(2rem, 4vw, 4rem);
}
.hero h1 { font-size: clamp(2rem, 5vw, 3.5rem); }
.hero .subtitle { font-size: clamp(1rem, 2vw, 1.25rem); color: var(--color-neutral-500, #5d6068); }

.features { padding-block: 3rem; }
.feature-card {
  padding: var(--space-6, 1.5rem);
  border-radius: var(--radius-lg, 12px);
  background: var(--color-neutral-50, #f8f8f8);
}

.pricing { padding-block: 3rem; }
.pricing-card {
  padding: 2rem;
  border-radius: var(--radius-lg, 12px);
  border: 1px solid var(--color-neutral-100, #e0dfdf);
  background: #fff;
}
.pricing-card.featured {
  border-color: var(--color-brand-primary, #1a73e8);
  border-width: 2px;
}

.testimonials { padding-block: 3rem; }
.testimonial { padding: 1.5rem; border-radius: var(--radius-md, 8px); background: #fff; }

.faq { padding-block: 3rem; max-width: 800px; margin-inline: auto; }
.faq details {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--color-neutral-100, #e0dfdf);
}
.faq summary {
  cursor: pointer;
  font-weight: 600;
  list-style: none;
}
.faq summary::-webkit-details-marker { display: none; }
.faq summary::after { content: "+"; float: right; transition: transform 0.15s ease; }
.faq details[open] summary::after { content: "−"; }

.nav { display: flex; align-items: center; gap: 1.5rem; flex-wrap: wrap; }
.nav a { text-decoration: none; }

.cookie-banner {
  position: fixed; left: 1rem; right: 1rem; bottom: 1rem;
  padding: 1rem 1.5rem;
  border-radius: var(--radius-md, 8px);
  background: var(--color-neutral-950, #11181c);
  color: #fff;
  display: flex; gap: 1rem; align-items: center; justify-content: space-between;
  z-index: 9999;
}
"""


def run(real_project_dir: Path, design_tokens: dict, llm: LLMClient) -> ConsolidateStats:
    stats = ConsolidateStats()
    css_dir = real_project_dir / "assets" / "css"
    raw_path = css_dir / "raw.css"
    if not raw_path.exists():
        stats.notes.append("raw.css not present; using deterministic fallback only")
        (css_dir / "base.css").write_text(FALLBACK_BASE_CSS, encoding="utf-8")
        (css_dir / "components.css").write_text(FALLBACK_COMPONENTS_CSS, encoding="utf-8")
        stats.base_bytes = len(FALLBACK_BASE_CSS)
        stats.components_bytes = len(FALLBACK_COMPONENTS_CSS)
        return stats

    raw_css = raw_path.read_text(encoding="utf-8", errors="ignore")
    stats.raw_bytes_in = len(raw_css)
    excerpt = raw_css[:MAX_RAW_CHARS]

    prompt = f"""\
{CONSOLIDATE_CSS_INSTRUCTIONS}

--- BEGIN INPUTS ---

DESIGN TOKENS (already exposed as CSS vars in tokens.css):
{json.dumps({"color": design_tokens.get("color"), "typography": {"families": (design_tokens.get("typography") or {}).get("families")}}, indent=2)[:3000]}

RAW CSS (concatenated + Angular-stripped; first {MAX_RAW_CHARS} chars):
{excerpt}

--- END INPUTS ---

Return ONLY the JSON object — no fence, no preamble.
"""

    try:
        reply = llm.ask(prompt, expect_json=True, max_tokens=10000)
    except Exception as e:
        log.warning(f"consolidate-css LLM call failed: {e}; using fallback")
        reply = None

    if not reply or not (reply.get("css") or "").strip():
        log.info("Writing deterministic fallback base.css + components.css")
        (css_dir / "base.css").write_text(FALLBACK_BASE_CSS, encoding="utf-8")
        (css_dir / "components.css").write_text(FALLBACK_COMPONENTS_CSS, encoding="utf-8")
        stats.base_bytes = len(FALLBACK_BASE_CSS)
        stats.components_bytes = len(FALLBACK_COMPONENTS_CSS)
        stats.notes.append("fell back to deterministic base + components")
        return stats

    base_css = reply.get("css") or ""
    # Even when the AI succeeds we keep our component skeletons available
    components_css = reply.get("components_css") or FALLBACK_COMPONENTS_CSS

    (css_dir / "base.css").write_text(base_css, encoding="utf-8")
    (css_dir / "components.css").write_text(components_css, encoding="utf-8")
    stats.base_bytes = len(base_css)
    stats.components_bytes = len(components_css)
    stats.kept_selectors = int(reply.get("kept_selectors") or 0)
    stats.notes.extend(reply.get("notes") or [])
    return stats
