"""
Preserve mode — keep the captured HTML + CSS intact so the rebuilt site
LOOKS IDENTICAL to the original.

This is the opposite philosophy from the AI-rewrite path: instead of
synthesising clean semantic HTML from scratch, we ship the SPA's actual
post-render DOM with just the bootstrap stripped away.

What we strip:
  - Angular / Webpack runtime scripts (the SPA tries to bootstrap and dies
    if the chunks are missing AND a <base href> exists)
  - <base href="/"> (we want relative paths)
  - <link rel="modulepreload"> / preload-of-script (chunks won't be there)
  - <noscript> "please enable JavaScript" blocks (the original page is
    already rendered; we don't want this to flash up)
  - The single most dangerous thing: inline <script> blocks that look
    like they call analytics, set cookies, or do Stripe/payment init.

What we KEEP:
  - Every <app-root>, <app-layout>, _nghost-* etc. attribute (Angular's
    view-encapsulation depends on these to apply styles)
  - All inline styles and inline <style> blocks
  - All <link rel="stylesheet">, <link rel="icon">, fonts
  - All visible content (text, images, buttons, forms)
  - All CSS classes (the captured CSS targets them)

What we REWRITE:
  - Every absolute asset URL (img src / link href / style url(...)) →
    local path under assets/ via the rewrite_assets map
  - Every absolute internal nav link (<a href="https://host/foo">) → the
    local <slug>.html equivalent
  - Form actions: original action moved to data-original-action; the
    runtime adds preventDefault. Never auto-rewires a form.

What we INJECT:
  - Our runtime.js at the bottom of <body> (purchase-warn, form-prevent,
    sticky-header, etc.)
  - A small inline CSS block to neutralise auto-opened popups / dialogs
    that the live SPA would have animated closed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)


# These patterns identify framework / runtime / chunk scripts we strip.
RUNTIME_SCRIPT_PATTERNS = [
    re.compile(r"runtime[-\.][\w]*\.js", re.I),
    re.compile(r"polyfills[-\.][\w]*\.js", re.I),
    re.compile(r"\bmain[-\.][\w]*\.js", re.I),
    re.compile(r"chunk-[\w]+\.js", re.I),
    re.compile(r"vendor[-\.][\w]*\.js", re.I),
    re.compile(r"webpack-runtime", re.I),
]

# Inline-script content that is unsafe to keep verbatim — analytics,
# Stripe init, cookie writers. We replace with a comment so the original
# layout doesn't shift.
UNSAFE_INLINE_SCRIPT_PATTERNS = [
    re.compile(r"google-analytics|gtag\(|GoogleAnalyticsObject", re.I),
    re.compile(r"\bdataLayer\b", re.I),
    re.compile(r"facebook\.net.*fbq", re.I | re.S),
    re.compile(r"hotjar|clarity\.ms|fullstory", re.I),
    re.compile(r"Stripe\(", re.I),
    re.compile(r"document\.cookie\s*=", re.I),
]


@dataclass
class PreserveStats:
    runtime_scripts_removed: int = 0
    preload_links_removed: int = 0
    base_removed: int = 0
    noscript_removed: int = 0
    inline_scripts_neutralised: int = 0
    asset_urls_rewritten: int = 0
    internal_links_rewritten: int = 0
    forms_dataified: int = 0
    purchase_buttons_tagged: int = 0
    dead_widgets_removed: int = 0
    bytes_in: int = 0
    bytes_out: int = 0


PURCHASE_TEXT_RE = re.compile(
    r"\b(buy(?:\s+now)?|purchase|checkout|pay\s+now|complete\s+order"
    r"|confirm\s+purchase|upgrade(?:\s+plan)?|add\s+credits?"
    r"|top[- ]?up|subscribe|start\s+trial|start\s+subscription"
    r"|place\s+order|submit\s+payment|add\s+to\s+cart)\b",
    re.I,
)


def _looks_purchase(el: Tag) -> bool:
    text = (el.get_text() or "").strip()
    if PURCHASE_TEXT_RE.search(text):
        return True
    aria = el.get("aria-label") or ""
    if PURCHASE_TEXT_RE.search(aria):
        return True
    classes = " ".join(el.get("class") or [])
    if PURCHASE_TEXT_RE.search(classes):
        return True
    return False


_REDACT_PATTERNS = [
    (re.compile(r"eyJ[A-Za-z0-9_\-+/=.]{20,}\.[A-Za-z0-9_\-+/=.]{6,}\.[A-Za-z0-9_\-+/=.]{6,}"), "[REDACTED-JWT]"),
    (re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{16,}"), "[REDACTED-STRIPE]"),
    (re.compile(r"pk_(?:live|test)_[A-Za-z0-9]{16,}"), "[REDACTED-STRIPE]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "[REDACTED-GITHUB]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-+/=]{20,}"), "Bearer [REDACTED]"),
]


def _strip_residual_secrets(html: str) -> str:
    for pat, repl in _REDACT_PATTERNS:
        html = pat.sub(repl, html)
    return html


def _matches_runtime(src: str) -> bool:
    return any(p.search(src) for p in RUNTIME_SCRIPT_PATTERNS)


def _expand_url_map(url_to_local: dict[str, str], base_origin: str) -> dict[str, str]:
    """Given the orchestrator's URL→local map (keyed on absolute URLs),
    derive the additional keys the captured HTML actually uses:
      * root-relative path  (/foo/bar.webp)
      * bare filename       (styles-RSVPYBKR.css)
      * protocol-relative   (//host/path)

    These cover the three common ways an SPA references local assets.
    """
    from urllib.parse import urlparse
    out: dict[str, str] = {}
    base_host = urlparse(base_origin).netloc.lower()
    for absolute, local in url_to_local.items():
        if local == absolute:  # cross-origin keep-as-is — don't expand
            continue
        out[absolute] = local
        try:
            p = urlparse(absolute)
        except Exception:
            continue
        if p.netloc.lower() != base_host:
            # Not same-host → only the absolute URL is canonical
            continue
        path = p.path or ""
        if not path:
            continue
        out[path] = local                 # /assets/img/foo.webp
        if path.startswith("/"):
            out[path[1:]] = local         # assets/img/foo.webp (no leading /)
        # protocol-relative
        out["//" + p.netloc + path] = local
        # bare filename (only useful for top-level assets like styles-xx.css)
        if "/" in path:
            bare = path.rsplit("/", 1)[-1]
            if bare and bare not in out:
                out[bare] = local
    return out


# Match an attribute value pointing at a captured asset. We only rewrite
# inside href/src/srcset/poster/style-url to avoid mangling free text that
# happens to contain a matching path fragment.
_ATTR_URL_RE = re.compile(
    r'(\b(?:href|src|poster|data-src|data-lazy-src|data-original|data-background-image|data-bg-image|data-bg-image-mobile|data-bg-image-tablet)\s*=\s*)(["\'])([^"\']+?)\2',
    re.I,
)
_SRCSET_RE = re.compile(r'(\bsrcset\s*=\s*)(["\'])([^"\']+?)\2', re.I)
_CSS_URL_RE = re.compile(r'url\(\s*([\'"]?)([^\'")\s]+?)\1\s*\)')


def _rewrite_asset_urls(html: str, url_to_local: dict[str, str], base_origin: str, stats: PreserveStats) -> str:
    """Substitute every URL/path in url_to_local with its local target.
    Operates on href/src/srcset/poster attrs and url(...) inside style
    blocks/attributes.
    """
    if not url_to_local:
        return html
    expanded = _expand_url_map(url_to_local, base_origin)
    count = 0

    def _lookup(raw: str) -> str | None:
        if not raw:
            return None
        raw = raw.strip()
        # Strip any cache-busting query/hash for the lookup but keep it on output
        bare = raw.split("?", 1)[0].split("#", 1)[0]
        for candidate in (raw, bare):
            if candidate in expanded:
                return expanded[candidate]
            # leading-slash variant
            if not candidate.startswith("/"):
                if "/" + candidate in expanded:
                    return expanded["/" + candidate]
        return None

    def _sub_attr(m: re.Match) -> str:
        prefix, q, val = m.group(1), m.group(2), m.group(3)
        local = _lookup(val)
        if not local:
            return m.group(0)
        nonlocal count
        count += 1
        return f'{prefix}{q}{local}{q}'

    def _sub_srcset(m: re.Match) -> str:
        prefix, q, val = m.group(1), m.group(2), m.group(3)
        parts = []
        changed = False
        for entry in val.split(","):
            tokens = entry.strip().split()
            if not tokens:
                continue
            url, *rest = tokens
            local = _lookup(url)
            if local:
                parts.append((local + " " + " ".join(rest)).rstrip())
                changed = True
            else:
                parts.append(entry.strip())
        if not changed:
            return m.group(0)
        nonlocal count
        count += 1
        return f'{prefix}{q}{", ".join(parts)}{q}'

    def _sub_css_url(m: re.Match) -> str:
        q, val = m.group(1), m.group(2)
        local = _lookup(val)
        if not local:
            return m.group(0)
        nonlocal count
        count += 1
        return f'url("{local}")'

    html = _ATTR_URL_RE.sub(_sub_attr, html)
    html = _SRCSET_RE.sub(_sub_srcset, html)
    html = _CSS_URL_RE.sub(_sub_css_url, html)
    stats.asset_urls_rewritten += count
    return html


def _rewrite_internal_links(
    soup: BeautifulSoup,
    base_origin: str,
    slug_by_url: dict[str, str],
    home_slug: str,
    stats: PreserveStats,
) -> None:
    """Rewrite every internal navigation link to point at the local .html
    file. Handles four shapes of `href` value:
      * absolute same-origin   https://host/foo  → foo.html
      * protocol-relative      //host/foo        → foo.html
      * root-relative          /foo              → foo.html
      * relative bare slug     foo               → foo.html  (only if it's
                                                   a known slug)
    Dead placeholder hrefs (`/null`, `javascript:void(0)`, empty) → `#`.
    """
    if not base_origin:
        return
    from urllib.parse import urlparse

    base_host = urlparse(base_origin).netloc.lower()
    # Index slugs by the path they came from
    slug_by_path: dict[str, str] = {}
    for u, slug in slug_by_url.items():
        try:
            p = urlparse(u)
            path = p.path.rstrip("/") or "/"
            if path not in slug_by_path:
                slug_by_path[path] = slug
        except Exception:
            continue
    # Also derive simple `/slug` paths so /order-list maps even though we
    # captured /order-list/market.
    for cap_url, slug in list(slug_by_url.items()):
        try:
            derived = "/" + slug.replace("__", "/")
            slug_by_path.setdefault(derived, slug)
        except Exception:
            continue

    def _resolve(slug: str) -> str:
        return "index.html" if slug == home_slug else f"{slug}.html"

    DEAD_HREF = ("/null", "javascript:", "")

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            a["href"] = "#"
            continue
        # Strip placeholder hrefs the captured SPA leaves around
        if href.endswith("/null") or href.startswith("javascript:"):
            a["href"] = "#"
            continue
        # tel: / mailto: / true external — leave alone
        if href.startswith(("tel:", "mailto:", "data:")):
            continue
        # Same-origin absolute
        target_slug: str | None = None
        if href.startswith(base_origin):
            try:
                path = urlparse(href).path.rstrip("/") or "/"
                target_slug = slug_by_path.get(path)
            except Exception:
                pass
        # Protocol-relative
        elif href.startswith("//"):
            try:
                p = urlparse("https:" + href)
                if p.netloc.lower() == base_host:
                    path = p.path.rstrip("/") or "/"
                    target_slug = slug_by_path.get(path)
            except Exception:
                pass
        # Root-relative (most common in this SPA)
        elif href.startswith("/"):
            path = href.split("?", 1)[0].split("#", 1)[0].rstrip("/") or "/"
            target_slug = slug_by_path.get(path)
        # External absolute → leave alone
        elif href.startswith(("http://", "https://")):
            continue
        # Hash-only — local anchor
        elif href.startswith("#"):
            continue
        # Plain "foo" — treat as relative; might be a slug
        else:
            target_slug = slug_by_path.get("/" + href.rstrip("/"))

        if target_slug:
            a["href"] = _resolve(target_slug)
            stats.internal_links_rewritten += 1


def _wire_orphan_anchors(soup: BeautifulSoup, stats: PreserveStats) -> None:
    """Anchors the SPA wired with `routerLink` arrive in the captured HTML
    with no `href`. Without one, clicking does nothing. Give the obvious
    cases sensible local hrefs:

      * <a class=logo|brand|navbar-brand>          → index.html
      * <a> containing "Back to Home" / "Home"     → index.html
      * <a> containing "Back" + an SVG arrow       → index.html (best guess)
      * any remaining <a> with no href             → href="#" so clicking
                                                     doesn't navigate to a 404
    """
    BACK_TEXT_RE = re.compile(r"^\s*(?:back(?:\s+to\s+home)?|home)\s*$", re.I)

    for a in list(soup.find_all("a")):
        if a.has_attr("href") and a["href"]:
            continue
        classes = " ".join(a.get("class") or []).lower()
        text = (a.get_text(strip=True) or "").strip()
        wired = False
        if re.search(r"\b(logo|brand|navbar-brand)\b", classes):
            a["href"] = "index.html"
            wired = True
        elif BACK_TEXT_RE.match(text):
            a["href"] = "index.html"
            wired = True
        elif a.find("svg") is not None and text and text.lower().startswith("back"):
            # "← Back" pattern with an icon
            a["href"] = "index.html"
            wired = True
        if wired:
            stats.internal_links_rewritten += 1
        else:
            # Don't leave it unclickable — but don't navigate either.
            a["href"] = "#"


def _strip_dead_widgets(soup: BeautifulSoup, stats: PreserveStats) -> None:
    """Remove SPA-only widgets whose interactive behavior can't be replicated
    without the original runtime. We don't fake them — leaving them in place
    teases the user with controls that look interactive but do nothing.

    Currently strips:
      * <app-cookies-bar>  — cookie banner (no real consent backend)
      * <app-feedback-button> — "Kind Feedback" floating button (would
                                open a server-backed feedback widget)
    """
    for selector in ("app-cookies-bar", "app-feedback-button"):
        for el in list(soup.find_all(selector)):
            el.decompose()
            stats.dead_widgets_removed += 1
    # Also drop any leftover bare cookie/consent dialog markup
    for el in list(soup.find_all(attrs={"class": re.compile(r"cookie[-_]?(?:bar|banner|notice|consent)", re.I)})):
        el.decompose()
        stats.dead_widgets_removed += 1


def preserve_page(
    *,
    slug: str,
    page_url: str,
    rendered_html: str,
    url_to_local: dict[str, str],
    slug_by_url: dict[str, str],
    base_origin: str,
    is_home: bool,
    home_slug: str = "home",
    real_project_dir: Path,
    extra_stylesheets: list[str] | None = None,
) -> tuple[Path, PreserveStats]:
    """Process one page. Returns (output_path, stats)."""
    stats = PreserveStats(bytes_in=len(rendered_html))
    soup = BeautifulSoup(rendered_html, "lxml")

    # 1. Strip Angular/webpack runtime scripts. Inline scripts that look
    # dangerous (analytics, Stripe, cookie-setting) get neutralised.
    for s in list(soup.find_all("script")):
        src = s.get("src") or ""
        if src and _matches_runtime(src):
            s.decompose()
            stats.runtime_scripts_removed += 1
            continue
        if not src:
            # inline script
            content = s.string or s.text or ""
            if any(p.search(content) for p in UNSAFE_INLINE_SCRIPT_PATTERNS):
                s.string = "/* dna-website: neutralised analytics/payment script */"
                stats.inline_scripts_neutralised += 1

    # 2. Strip preload-of-script links and modulepreload
    for lk in list(soup.find_all("link")):
        rel = " ".join(lk.get("rel") or []).lower()
        as_attr = (lk.get("as") or "").lower()
        href = lk.get("href") or ""
        if "modulepreload" in rel or ("preload" in rel and as_attr == "script"):
            lk.decompose()
            stats.preload_links_removed += 1
        elif "preload" in rel and _matches_runtime(href):
            lk.decompose()
            stats.preload_links_removed += 1

    # 3. Strip <base href="/">
    for tag in list(soup.find_all("base")):
        tag.decompose()
        stats.base_removed += 1

    # 4. Strip "please enable JS" noscript
    for tag in list(soup.find_all("noscript")):
        text = (tag.get_text(strip=True) or "").lower()
        if "enable" in text and "javascript" in text:
            tag.decompose()
            stats.noscript_removed += 1

    # 5. Forms — preserve all markup, just intercept the submit
    for form in soup.find_all("form"):
        original = form.get("action") or ""
        if original:
            form["data-original-action"] = original
        # Disable native submit; the runtime warns instead.
        form["action"] = "#"
        form["onsubmit"] = "return false;"
        stats.forms_dataified += 1

    # 6. Purchase buttons — leave content intact, tag for the runtime
    for el in soup.find_all(["button", "a"]):
        if _looks_purchase(el):
            existing = el.get("data-todo") or ""
            if "needs-operator-wiring" not in existing:
                el["data-todo"] = (existing + " needs-operator-wiring").strip()
            stats.purchase_buttons_tagged += 1

    # 6b. Strip dead SPA-only widgets (cookie banner, feedback button — they
    # rendered fine but their click handlers can't work without the runtime).
    _strip_dead_widgets(soup, stats)

    # 7a. Internal link rewrite (absolute + protocol-relative + root-relative)
    _rewrite_internal_links(soup, base_origin, slug_by_url, home_slug, stats)

    # 7b. Wire up orphan anchors (Angular routerLink left them with no href)
    _wire_orphan_anchors(soup, stats)

    # 8. Inject our normalizer runtime.js right before </body>
    if soup.body is not None:
        rt = soup.new_tag("script", src="assets/js/runtime.js", defer="")
        soup.body.append(rt)

    # 9. Add a small style block to undo any "open by default" SPA state
    # that the live runtime would have collapsed on hover-out
    if soup.head is not None:
        style = soup.new_tag("style")
        style.string = (
            "\n/* dna-website normalizer: hide modal/popup elements that the original "
            "SPA would have collapsed at runtime */\n"
            "[role=dialog][open], [aria-modal=true] { display: none; }\n"
            "dialog:not([open]) { display: none; }\n"
        )
        soup.head.append(style)

    # 10. Re-stringify and rewrite asset URLs (cheaper as text op than DOM)
    html = str(soup)
    html = _rewrite_asset_urls(html, url_to_local, base_origin, stats)
    html = _strip_residual_secrets(html)
    stats.bytes_out = len(html)

    # 11. Write output
    out_name = "index.html" if is_home else f"{slug}.html"
    out_path = real_project_dir / out_name
    out_path.write_text(html, encoding="utf-8")
    return out_path, stats
