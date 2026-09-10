"""
Per-page AI-powered HTML generation.

For each captured page:
  1. Read the SPA-stripped HTML (post strip_spa)
  2. Read the page's section/link/CTA inventory from _inbox/<slug>.json
  3. Read the page's interactive-map entry
  4. Send to Claude with the GENERATE_PAGE_HTML_INSTRUCTIONS prompt
  5. Validate the response JSON
  6. Rewrite asset URLs (deterministic, using rewrite_assets map)
  7. Write index.html / <slug>.html in the real-project dir
  8. Write per-page CSS/JS if the AI emitted any

The LLM never writes asset paths directly; it leaves
`src="<ORIGINAL-URL>"` and we substitute via the asset map after-the-fact.
This keeps URL rewriting deterministic and testable.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from .llm import LLMClient
from .prompts import GENERATE_PAGE_HTML_INSTRUCTIONS
from .strip_spa import strip_spa

log = logging.getLogger(__name__)


@dataclass
class PageGenStats:
    pages_generated: int = 0
    bytes_html_written: int = 0
    bytes_css_written: int = 0
    bytes_js_written: int = 0
    todos_collected: list[dict] = field(default_factory=list)
    notes_collected: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)


# Maximum characters of the original HTML we send to the LLM. Above this
# we excerpt + summarise. 20k chars ≈ 5k tokens — keeps per-page calls in
# the 15-30 s range. The structural-sections summary in the user prompt
# carries the bulk of the semantic info; we don't need every <span> here.
MAX_HTML_CHARS = 20_000


def _excerpt_html(html: str, max_chars: int = MAX_HTML_CHARS) -> str:
    """If the HTML is small enough, return as-is. Otherwise return a
    head-and-tail excerpt that preserves the structural shell + a
    representative middle slice."""
    if len(html) <= max_chars:
        return html
    soup = BeautifulSoup(html, "lxml")
    # Try to preserve a structural skeleton: <head> + <body>'s direct
    # children outline + the first few <section>s in full.
    head = soup.find("head")
    head_text = str(head)[:8000] if head else ""
    body = soup.find("body")
    if not body:
        return html[:max_chars]
    out = ["<!-- excerpt: structural --><html>" + head_text + "<body>"]
    char_budget = max_chars - len(head_text) - 1000
    for child in body.find_all(recursive=False):
        chunk = str(child)
        if len(chunk) > char_budget:
            # Truncate but keep the opening tag intact for context
            tagopen = re.match(r"^<[^>]+>", chunk)
            opener = tagopen.group(0) if tagopen else ""
            out.append(opener + "\n<!-- truncated -->\n")
            break
        out.append(chunk)
        char_budget -= len(chunk)
        if char_budget <= 0:
            break
    out.append("</body></html>")
    return "\n".join(out)


def _rewrite_asset_urls(html: str, url_to_local: dict[str, str], page_path: str = "") -> str:
    """Substitute every absolute asset URL in the HTML with its local
    rewrite target. Pure-text find/replace is safer than full DOM
    rewriting for URLs the AI might emit in non-standard attributes."""
    if not url_to_local:
        return html
    # Sort by length descending so longer URLs get replaced before any
    # substring matches kick in.
    for src in sorted(url_to_local.keys(), key=len, reverse=True):
        local = url_to_local[src]
        if local == src:  # cross-origin keep-as-is
            continue
        html = html.replace(src, local)
    return html


def rewrite_internal_links(
    html: str,
    base_origin: str,
    slug_by_url: dict[str, str],
    home_slug: str = "home",
) -> str:
    """Convert absolute same-origin URLs in <a href> attributes to relative
    local HTML files. e.g. https://kindskiptracing.com/about-us → about-us.html.

    `slug_by_url` is a mapping built by the orchestrator from captures.json.
    URLs not in the map are left alone (they may be deep links to pages we
    didn't capture).
    """
    if not slug_by_url:
        return html
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith(base_origin):
            continue
        target = slug_by_url.get(href.rstrip("/")) or slug_by_url.get(href)
        if not target:
            continue
        a["href"] = "index.html" if target == home_slug else f"{target}.html"
    return str(soup)


def _strip_residual_secrets(html: str) -> str:
    """A second sweep over the AI-generated HTML to ensure no token-shaped
    strings made it through. The LLM is asked to redact in the prompt
    too — this is belt-and-suspenders."""
    patterns = [
        (re.compile(r"eyJ[A-Za-z0-9_\-+/=.]{20,}\.[A-Za-z0-9_\-+/=.]{6,}\.[A-Za-z0-9_\-+/=.]{6,}"), "[REDACTED-JWT]"),
        (re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{16,}"), "[REDACTED-STRIPE]"),
        (re.compile(r"pk_(?:live|test)_[A-Za-z0-9]{16,}"), "[REDACTED-STRIPE]"),
        (re.compile(r"Bearer\s+[A-Za-z0-9._\-+/=]{20,}"), "Bearer [REDACTED]"),
    ]
    for pat, repl in patterns:
        html = pat.sub(repl, html)
    return html


def _build_page_prompt(
    slug: str,
    page_url: str,
    stripped_html: str,
    inbox_payload: dict,
    interactive_map_entry: dict | None,
) -> str:
    """Construct the user prompt for one page."""
    sections = inbox_payload.get("sections") or []
    compact = inbox_payload.get("compact_styles") or {}
    return f"""\
{GENERATE_PAGE_HTML_INSTRUCTIONS}

--- BEGIN PAGE INPUTS ---

slug: {slug}
url: {page_url}

# Captured sections (headings / paragraphs / links / CTAs / images):
{json.dumps(sections, indent=2)[:8000]}

# Interactive map entry for this page (links / buttons / forms / iframes):
{json.dumps(interactive_map_entry or {}, indent=2)[:8000]}

# Compact computed-style stats (top-N values per property):
{json.dumps({k: compact.get(k) for k in ("font_families", "font_sizes", "font_weights", "colors", "radii", "shadows")}, indent=2)[:4000]}

# Stripped HTML (SPA wrappers removed; asset URLs preserved verbatim so
# they can be substituted to local paths after generation):
{_excerpt_html(stripped_html)}

--- END PAGE INPUTS ---

Reminder: return ONLY the JSON object — no markdown fence, no preamble.
"""


def generate_page(
    *,
    slug: str,
    page_url: str,
    rendered_html: str,
    inbox_payload: dict,
    interactive_map_entry: dict | None,
    url_to_local: dict[str, str],
    real_project_dir: Path,
    llm: LLMClient,
    is_home: bool = False,
    slug_by_url: dict[str, str] | None = None,
    base_origin: str = "",
) -> dict:
    """Generate one page. Writes files. Returns a summary dict."""
    # 1. Deterministic SPA strip
    stripped, strip_stats = strip_spa(rendered_html)

    # 2. Ask the LLM
    prompt = _build_page_prompt(slug, page_url, stripped, inbox_payload, interactive_map_entry)
    used_fallback = False
    try:
        reply = llm.ask(prompt, expect_json=True)
    except Exception as e:
        log.error(f"LLM call failed for {slug}: {e}")
        reply = {}
        used_fallback = True
        fallback_reason = f"LLM call failed: {e}"

    html = reply.get("html") or ""
    page_css = reply.get("page_css") or ""
    page_js = reply.get("page_js") or ""
    notes = list(reply.get("notes") or [])
    todos = list(reply.get("todos") or [])

    # If the AI returned empty HTML (or we already used the fallback path),
    # synthesize from the captured inbox sections deterministically.
    if not html.strip():
        html = _fallback_html(slug, page_url, inbox_payload)
        used_fallback = True
        notes.append("deterministic fallback used (no AI HTML)")

    # 3a. Deterministic asset URL rewrite
    html = _rewrite_asset_urls(html, url_to_local)

    # 3b. Internal-link rewrite (absolute same-origin → relative html files)
    if slug_by_url and base_origin:
        html = rewrite_internal_links(html, base_origin, slug_by_url)

    # 4. Residual secret sweep
    html = _strip_residual_secrets(html)

    # 5. Write files
    fname = "index.html" if is_home else f"{slug}.html"
    out_path = real_project_dir / fname
    out_path.write_text(html, encoding="utf-8")

    css_path = None
    if page_css.strip():
        pages_css_dir = real_project_dir / "assets" / "css" / "pages"
        pages_css_dir.mkdir(parents=True, exist_ok=True)
        css_path = pages_css_dir / f"{slug}.css"
        css_path.write_text(page_css, encoding="utf-8")

    js_path = None
    if page_js.strip():
        pages_js_dir = real_project_dir / "assets" / "js" / "pages"
        pages_js_dir.mkdir(parents=True, exist_ok=True)
        js_path = pages_js_dir / f"{slug}.js"
        js_path.write_text(page_js, encoding="utf-8")

    return {
        "slug": slug,
        "url": page_url,
        "html_path": str(out_path.relative_to(real_project_dir)),
        "css_path": str(css_path.relative_to(real_project_dir)) if css_path else None,
        "js_path": str(js_path.relative_to(real_project_dir)) if js_path else None,
        "html_bytes": len(html),
        "notes": notes,
        "todos": todos,
        "strip_stats": {
            "scripts_removed": strip_stats.scripts_removed,
            "preload_links_removed": strip_stats.preload_links_removed,
            "ng_attrs_removed": strip_stats.ng_attrs_removed,
            "spa_elements_renamed": dict(strip_stats.spa_elements_renamed),
        },
    }


PURCHASE_BUTTON_RE = re.compile(
    r"\b(buy|purchase|checkout|pay\s*now|complete\s+order|confirm\s+purchase"
    r"|upgrade(?:\s+plan)?|add\s+credits?|top[- ]?up|subscribe"
    r"|start\s+trial|start\s+subscription|place\s+order|submit\s+payment"
    r"|add\s+to\s+cart)\b",
    re.I,
)


def _looks_like_purchase(text: str | None) -> bool:
    if not text:
        return False
    return bool(PURCHASE_BUTTON_RE.search(text))


def _fallback_html(slug: str, page_url: str, inbox_payload: dict) -> str:
    """Deterministic fallback: build a clean semantic page from the
    captured inbox sections. Used both when the LLM call fails and when
    running in --mock mode so the output is always browsable.
    """
    import html as h
    meta = inbox_payload.get("meta") or {}
    title = h.escape(meta.get("title") or slug)
    desc = h.escape(meta.get("description") or "")
    sections = inbox_payload.get("sections") or []
    links = inbox_payload.get("links") or []
    image_urls = inbox_payload.get("image_urls") or []

    # Build a tiny <header><nav> from the in-scope links (dedup by path)
    nav_items: list[tuple[str, str]] = []
    seen = set()
    for s in sections:
        for lk in (s.get("links") or []):
            href = lk.get("href") or ""
            text = (lk.get("text") or "").strip()
            if not text or not href:
                continue
            key = (href, text)
            if key in seen:
                continue
            seen.add(key)
            nav_items.append((href, text))
    nav_html_parts = []
    for href, text in nav_items[:8]:
        nav_html_parts.append(f'<a href="{h.escape(href)}">{h.escape(text)}</a>')
    nav_html = "\n        ".join(nav_html_parts)

    # Sections
    sec_parts = []
    for i, sec in enumerate(sections):
        sec_class = "hero" if i == 0 else "section"
        sec_parts.append(f'<section class="{sec_class}">')
        if sec.get("heading"):
            lvl = sec.get("level") or 2
            sec_parts.append(f"  <h{lvl}>{h.escape(sec['heading'])}</h{lvl}>")
        for p in sec.get("paragraphs") or []:
            sec_parts.append(f"  <p>{h.escape(p)}</p>")
        # Images
        for img in (sec.get("images") or [])[:6]:
            src = img.get("src") or ""
            alt = img.get("alt") or ""
            if src:
                sec_parts.append(f'  <img src="{h.escape(src)}" alt="{h.escape(alt)}">')
        # CTAs
        if sec.get("ctas"):
            sec_parts.append('  <div class="cta-row flex">')
            for cta in sec.get("ctas") or []:
                text = (cta.get("text") or "").strip()
                href = cta.get("href") or "#"
                if not text:
                    continue
                cls = "btn btn-primary" if cta.get("kind") == "button" else "btn btn-secondary"
                attrs = ""
                if _looks_like_purchase(text):
                    attrs = ' data-todo="needs-operator-wiring"'
                # Convert /null and javascript:* placeholders to a no-op #
                if href.endswith("/null") or href.startswith("javascript:"):
                    href = "#"
                sec_parts.append(f'    <a class="{cls}" href="{h.escape(href)}"{attrs}>{h.escape(text)}</a>')
            sec_parts.append('  </div>')
        sec_parts.append('</section>')
    sec_html = "\n".join(sec_parts)

    # Compose final HTML
    return f"""<!DOCTYPE html>
<html lang="{h.escape(meta.get('lang') or 'en')}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{desc}">
  <link rel="stylesheet" href="assets/css/tokens.css">
  <link rel="stylesheet" href="assets/css/reset.css">
  <link rel="stylesheet" href="assets/css/base.css">
  <link rel="stylesheet" href="assets/css/components.css">
  <link rel="stylesheet" href="assets/css/runtime.css">
</head>
<body data-page="{h.escape(slug)}">
  <header>
    <div class="container nav">
      <a href="index.html" class="logo">{h.escape(meta.get('og', {}).get('site_name') or meta.get('title') or slug)}</a>
      <nav class="primary">
        {nav_html}
      </nav>
    </div>
  </header>

  <main class="container">
    {sec_html}
  </main>

  <footer>
    <div class="container">
      <p>Static clone normalized by dna-website. <a href="index.html">Home</a></p>
    </div>
  </footer>

  <script src="assets/js/runtime.js" defer></script>
</body>
</html>"""
