"""
Derive a normalized "design blueprint" from a capture's HTML + CSS.

Output: analysis/design-blueprint.json

Python port (extended) of webapp-clone-pipeline/src/builder/wp-blueprint/
design-from-html.js. The original v1 file classifies colors into semantic
roles (primary/secondary/accent/background/text/headingText/headerBg/
footerBg) plus button styles, which is what a rebuild agent actually wants.

We layer this on top of analyze_dna's raw clusters: the cluster output is
the truth, the blueprint is the *opinionated normalization* a rebuild
template can directly consume.

Where this is stronger than the raw analyze_dna output:
  - Button color comes from elements that actually look like buttons
    (.btn, [class*=button], <button>) — 25x weight in ranking.
  - Header/footer bg colors read directly from <header>/<footer> inline
    style attributes (best-effort, but catches the common case).
  - Google Fonts <link> family names are extracted directly, so heading +
    body family come back as plain font names instead of stack soup.
  - Defaults are sensible (Montserrat/OpenSans/Tailwind blue) when a real
    site provides no signal — saves the rebuild agent guessing.

Usage:
  python -m scripts.build_blueprint --out outputs/<run>
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


HEX_OR_RGB_RE = re.compile(r"#[0-9a-f]{3,8}\b|rgba?\([^)]+\)", re.I)


def rgb_to_hex(rgb: str) -> str | None:
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", rgb, re.I)
    if not m:
        return None
    r, g, b = (int(m.group(i)) for i in (1, 2, 3))
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def normalize_color(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if v.startswith("#"):
        if len(v) == 4:
            return "#" + "".join(c * 2 for c in v[1:]).lower()
        return v[:7].lower()
    if v.startswith("rgb"):
        out = rgb_to_hex(v)
        return out.lower() if out else None
    return None


def color_stats(hex_color: str) -> tuple[float, float]:
    r = int(hex_color[1:3], 16) / 255
    g = int(hex_color[3:5], 16) / 255
    b = int(hex_color[5:7], 16) / 255
    mx = max(r, g, b); mn = min(r, g, b)
    luminance = (mx + mn) / 2
    if mx == mn:
        sat = 0.0
    elif luminance > 0.5:
        sat = (mx - mn) / (2 - mx - mn)
    else:
        sat = (mx - mn) / (mx + mn) if (mx + mn) else 0.0
    return luminance, sat


def is_interesting(hex_color: str | None) -> bool:
    if not hex_color or len(hex_color) < 7:
        return False
    try:
        lum, sat = color_stats(hex_color)
    except Exception:
        return False
    if lum < 0.04 or lum > 0.96:
        return False
    if sat < 0.12:
        return False
    return True


def gather_inline_css(soup) -> str:
    parts = []
    for s in soup.find_all("style"):
        if s.string:
            parts.append(s.string)
        elif s.text:
            parts.append(s.text)
    for el in soup.find_all(style=True):
        parts.append(el.get("style") or "")
    return "\n".join(parts)


def gather_linked_css(out_dir: Path, manifest: dict) -> str:
    """Concatenate every downloaded .css asset's content into a single string
    (capped at 1.5MB to bound memory).
    """
    assets = (manifest or {}).get("assets") or []
    chunks: list[str] = []
    total = 0
    for a in assets:
        ct = (a.get("content_type") or "").lower()
        ext = ""
        lp = a.get("local_path") or ""
        if lp:
            ext = lp.lower().rsplit(".", 1)[-1] if "." in lp else ""
        is_css = ct.startswith("text/css") or ext == "css" or lp.endswith(".css")
        if not is_css or not lp:
            continue
        path = out_dir / lp
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            chunks.append(text)
            total += len(text)
            if total > 1_500_000:
                break
        except Exception:
            continue
    return "\n".join(chunks)


def gather_button_context_colors(soup) -> list[str]:
    out: list[str] = []
    sel = 'a.btn, a.button, button, [class*="btn-"], [class*="button"], .wp-block-button__link, [class*="cta"]'
    for el in soup.select(sel):
        style = el.get("style") or ""
        for m in HEX_OR_RGB_RE.findall(style):
            out.append(m)
        # Also pull from any inline computed style attributes
    return out


def rank_colors(css_text: str, button_colors: list[str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for m in HEX_OR_RGB_RE.findall(css_text or ""):
        hx = normalize_color(m)
        if not is_interesting(hx):
            continue
        counts[hx] = counts.get(hx, 0) + 1
    for c in button_colors:
        hx = normalize_color(c)
        if is_interesting(hx):
            counts[hx] = counts.get(hx, 0) + 25
    return sorted(counts.items(), key=lambda kv: -kv[1])


def parse_google_fonts(soup) -> dict:
    families = []
    for lk in soup.find_all("link"):
        href = lk.get("href") or ""
        if "fonts.googleapis" not in href:
            continue
        for m in re.finditer(r"family=([^&:]+)", href):
            fam = m.group(1).replace("+", " ")
            fam = fam.split(":")[0].strip()
            if fam:
                families.append(fam)
    fontface = []
    for m in re.finditer(r"@font-face\s*\{[^}]*\}", str(soup)):
        f = re.search(r"font-family\s*:\s*['\"]?([^;'\"\n]+)", m.group(0), re.I)
        if f:
            fontface.append(f.group(1).strip())
    return {"google": families, "fontface": fontface}


def peek_body_colors(soup) -> dict:
    def pluck(tag: str, prop: str) -> str | None:
        el = soup.find(tag)
        if not el:
            return None
        style = el.get("style") or ""
        # Word-boundary the property name so "color:" doesn't also match
        # "background-color:". `(?:^|;|\s)` ensures the prop sits at the
        # start of a declaration, not the tail of another one.
        m = re.search(rf"(?:^|;)\s*{re.escape(prop)}\s*:\s*([^;]+)", style, re.I)
        return m.group(1).strip() if m else None
    header = soup.find("header")
    header_cls = " ".join(header.get("class") or []) if header else ""
    header_pos = "sticky" if re.search(r"sticky|fixed", header_cls, re.I) else None
    return {
        "body_bg": pluck("body", "background-color"),
        "body_color": pluck("body", "color"),
        "header_bg": pluck("header", "background-color"),
        "footer_bg": pluck("footer", "background-color"),
        "header_pos": header_pos,
    }


DEFAULTS = {
    "colors": {
        "primary": "#1a73e8",
        "secondary": "#333333",
        "accent": "#1a73e8",
        "background": "#ffffff",
        "text": "#222222",
        "heading_text": "#111111",
        "header_bg": "#ffffff",
        "footer_bg": "#1a1a1a",
    },
    "fonts": {
        "heading": {"family": "Montserrat", "weight": "700", "source": "system"},
        "body": {"family": "Open Sans", "weight": "400", "source": "system"},
    },
}


def derive(out_dir: Path) -> dict:
    from bs4 import BeautifulSoup

    pages_dir = out_dir / "raw" / "pages"
    home_html = None
    # Pick the home page first; fall back to the first available page.
    for candidate_slug in ("home", "index"):
        p = pages_dir / candidate_slug / "rendered.html"
        if p.exists():
            home_html = p.read_text(encoding="utf-8", errors="ignore")
            break
    if home_html is None and pages_dir.exists():
        for pd in sorted(pages_dir.iterdir()):
            rh = pd / "rendered.html"
            if rh.exists():
                home_html = rh.read_text(encoding="utf-8", errors="ignore")
                break
    if not home_html:
        # Defaults
        return {**DEFAULTS, "header": {"style": "static", "transparent": False, "height": "80px"},
                "layout": {"max_width": "1200px", "style": "boxed"}, "warnings": ["no home HTML found; defaults used"]}

    soup = BeautifulSoup(home_html, "lxml")

    # Manifest for CSS resolution
    manifest_path = out_dir / "asset_manifest.json"
    manifest = {}
    if manifest_path.exists():
        try: manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception: pass

    inline_css = gather_inline_css(soup)
    linked_css = gather_linked_css(out_dir, manifest)
    css_text = (inline_css + "\n" + linked_css)[:1_500_000]

    button_colors = gather_button_context_colors(soup)
    ranked = rank_colors(css_text, button_colors)

    primary = ranked[0][0] if ranked else None
    secondary = next((c for c, _ in ranked if c != primary), None)
    accent = next((c for c, _ in ranked if c != primary and c != secondary), None)

    fonts = parse_google_fonts(soup)
    peek = peek_body_colors(soup)

    heading_family = (fonts["google"][0] if fonts["google"] else None) or (fonts["fontface"][0] if fonts["fontface"] else None)
    body_family = (fonts["google"][1] if len(fonts["google"]) > 1 else None) \
                  or (fonts["google"][0] if fonts["google"] else None) \
                  or (fonts["fontface"][0] if fonts["fontface"] else None)

    # Cross-validate against analyze_dna's design-tokens.json — if our heuristic
    # primary disagrees with the LAB-clustered brand.primary, prefer the
    # clustered one (it's more rigorous). Keep the heuristic value as
    # alternates[].
    alternates: list[str] = []
    tokens_path = out_dir / "analysis" / "design-tokens.json"
    if tokens_path.exists():
        try:
            tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
            brand_prim = ((tokens.get("color") or {}).get("brand") or {}).get("primary") or {}
            clustered_primary = (brand_prim.get("value") or "").lower()
            if clustered_primary:
                if primary and primary.lower() != clustered_primary:
                    alternates.append(primary)
                primary = clustered_primary
        except Exception:
            pass

    return {
        "metadata": {
            "generated_at": datetime.utcnow().isoformat(),
            "agent": "dna-website/build_blueprint v0.2",
            "source": "raw/pages/home/rendered.html + linked CSS",
        },
        "colors": {
            "primary": primary or DEFAULTS["colors"]["primary"],
            "secondary": secondary or DEFAULTS["colors"]["secondary"],
            "accent": accent or primary or DEFAULTS["colors"]["accent"],
            "background": normalize_color(peek["body_bg"]) or DEFAULTS["colors"]["background"],
            "text": normalize_color(peek["body_color"]) or DEFAULTS["colors"]["text"],
            "heading_text": normalize_color(peek["body_color"]) or DEFAULTS["colors"]["heading_text"],
            "header_bg": normalize_color(peek["header_bg"]) or DEFAULTS["colors"]["header_bg"],
            "footer_bg": normalize_color(peek["footer_bg"]) or DEFAULTS["colors"]["footer_bg"],
            "alternates": alternates,
        },
        "fonts": {
            "heading": {
                "family": heading_family or DEFAULTS["fonts"]["heading"]["family"],
                "weight": "700",
                "source": "google" if fonts["google"] else "system",
            },
            "body": {
                "family": body_family or DEFAULTS["fonts"]["body"]["family"],
                "weight": "400",
                "source": "google" if fonts["google"] else "system",
            },
        },
        "buttons": {
            "primary": {
                "bg": primary or DEFAULTS["colors"]["primary"],
                "text": "#ffffff",
                "border_radius": "4px",
                "padding": "12px 24px",
                "font_weight": "600",
            },
            "secondary": {
                "bg": "transparent",
                "text": primary or DEFAULTS["colors"]["primary"],
                "border": f"2px solid {primary or DEFAULTS['colors']['primary']}",
                "border_radius": "4px",
            },
        },
        "header": {
            "style": "sticky" if peek["header_pos"] == "sticky" else "static",
            "transparent": False,
            "height": "80px",
        },
        "layout": {"max_width": "1200px", "style": "boxed"},
        "ranking_topN": [{"color": c, "freq": f} for c, f in ranked[:12]],
        "google_fonts_detected": fonts["google"],
        "fontface_families_detected": fonts["fontface"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out_dir = Path(args.out).resolve()
    bp = derive(out_dir)
    analysis_dir = out_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    target = analysis_dir / "design-blueprint.json"
    target.write_text(json.dumps(bp, indent=2), encoding="utf-8")
    print(f"design-blueprint: primary={bp['colors']['primary']} "
          f"secondary={bp['colors']['secondary']} accent={bp['colors']['accent']} "
          f"heading={bp['fonts']['heading']['family']}/{bp['fonts']['heading']['source']} "
          f"body={bp['fonts']['body']['family']}/{bp['fonts']['body']['source']} -> {target}")


if __name__ == "__main__":
    main()
