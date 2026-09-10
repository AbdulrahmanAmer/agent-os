"""
Deterministic SPA wrapper removal.

Runs BEFORE the AI-powered HTML generator. Strips obvious Angular /
React / Vue runtime artifacts from the captured HTML so the LLM sees
cleaner input and spends fewer tokens reasoning about scaffolding.

What gets removed:
  - <script src="*runtime*.js">, <script src="*polyfills*.js">,
    <script src="*main*.js">, <script src="*chunk-*.js"> (Angular/Webpack)
  - <link rel="modulepreload" href="*.js">
  - <link rel="preload" as="script" href="*.js">
  - Angular custom-element NAMES are kept but flagged for the LLM to
    decide what to do (we don't unconditionally rewrite them — context
    matters).
  - data-ng-*, _nghost-*, _ngcontent-*, ng-* attributes
  - <noscript>...</noscript> blocks that just say "enable JS"
  - <base href="/"> (we want relative paths in the static project)

What gets preserved:
  - All visible text content
  - All <img>, <a>, <button>, <form>, <iframe>, headings, paragraphs
  - All inline <style> blocks (those will be consolidated downstream)
  - All <link rel="stylesheet">
  - All non-runtime <script> (analytics, third-party widgets are kept
    so the LLM can decide whether to keep or strip)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag


RUNTIME_SCRIPT_PATTERNS = [
    re.compile(r"runtime[-\.][\w]*\.js", re.I),
    re.compile(r"polyfills[-\.][\w]*\.js", re.I),
    re.compile(r"\bmain[-\.][\w]*\.js", re.I),
    re.compile(r"chunk-[\w]+\.js", re.I),
    re.compile(r"webpack-runtime", re.I),
    re.compile(r"scripts[-\.][\w]*\.js$", re.I),
    re.compile(r"vendor[-\.][\w]*\.js", re.I),
]

NG_ATTR_RE = re.compile(r"^(_ng(?:host|content)-|data-ng-|ng-)", re.I)


@dataclass
class StripStats:
    scripts_removed: int = 0
    preload_links_removed: int = 0
    ng_attrs_removed: int = 0
    noscript_removed: int = 0
    base_removed: int = 0
    spa_elements_renamed: dict[str, str] = field(default_factory=dict)
    bytes_before: int = 0
    bytes_after: int = 0


SPA_ELEMENT_RENAMES = {
    # Angular custom elements: map to semantic tags. We're cautious here —
    # only rename when the role is unambiguous.
    "app-root": "div",
    "app-layout": "div",
    "app-header": "header",
    "app-footer": "footer",
    "app-nav": "nav",
    "app-main": "main",
    "app-page": "main",
    "app-section": "section",
    "app-article": "article",
    "app-aside": "aside",
}


def _is_runtime_script_src(src: str) -> bool:
    return any(p.search(src) for p in RUNTIME_SCRIPT_PATTERNS)


def strip_spa(html: str) -> tuple[str, StripStats]:
    """Strip SPA scaffolding from an HTML string. Returns (clean_html, stats)."""
    stats = StripStats()
    stats.bytes_before = len(html)

    soup = BeautifulSoup(html, "lxml")

    # 1. Remove SPA runtime / chunk scripts
    for tag in list(soup.find_all("script")):
        src = tag.get("src") or ""
        if src and _is_runtime_script_src(src):
            tag.decompose()
            stats.scripts_removed += 1

    # 2. Remove modulepreload / preload of scripts (Angular emits these)
    for tag in list(soup.find_all("link")):
        rel = " ".join(tag.get("rel") or []).lower()
        as_attr = (tag.get("as") or "").lower()
        href = tag.get("href") or ""
        if "modulepreload" in rel:
            tag.decompose()
            stats.preload_links_removed += 1
            continue
        if "preload" in rel and as_attr == "script":
            tag.decompose()
            stats.preload_links_removed += 1
            continue
        if "preload" in rel and _is_runtime_script_src(href):
            tag.decompose()
            stats.preload_links_removed += 1

    # 3. Remove <base href="/"> — we want relative paths in the static project
    for tag in list(soup.find_all("base")):
        tag.decompose()
        stats.base_removed += 1

    # 4. Remove "enable JavaScript" noscript blocks
    for tag in list(soup.find_all("noscript")):
        text = (tag.get_text(strip=True) or "").lower()
        if "enable" in text and ("javascript" in text or "js" in text):
            tag.decompose()
            stats.noscript_removed += 1

    # 5. Strip Angular metadata attributes site-wide. Don't touch text.
    for el in soup.find_all(True):
        if not isinstance(el, Tag):
            continue
        for attr in list(el.attrs.keys()):
            if NG_ATTR_RE.match(attr):
                del el.attrs[attr]
                stats.ng_attrs_removed += 1

    # 6. Rename SPA custom elements to semantic equivalents where safe
    for src_tag, dst_tag in SPA_ELEMENT_RENAMES.items():
        for el in soup.find_all(src_tag):
            el.name = dst_tag
            stats.spa_elements_renamed[src_tag] = stats.spa_elements_renamed.get(src_tag, 0) + 1
    # Also handle other app-* custom elements: keep them but downgrade to <div>.
    # The LLM will give them meaningful semantics in its rewrite.
    for el in soup.find_all():
        if not isinstance(el, Tag):
            continue
        name = el.name or ""
        if name.startswith("app-") and name not in SPA_ELEMENT_RENAMES:
            el.name = "div"
            stats.spa_elements_renamed[name] = stats.spa_elements_renamed.get(name, 0) + 1
        # Strip Angular-injected event attributes too (onclick="ng_...")
        if "onclick" in el.attrs and "ng" in (el.attrs.get("onclick") or "").lower()[:30]:
            del el.attrs["onclick"]

    cleaned = str(soup)
    stats.bytes_after = len(cleaned)
    return cleaned, stats
