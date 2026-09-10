"""
Save a compact-format page capture (aggregated style stats + structured
sections) to disk in the dna-website output layout. Used by the
Chrome-MCP-driven crawl path.

Input JSON shape (passed via --file or stdin):
  {
    "url": "https://...",
    "slug": "home" | null,
    "final_url": "...",
    "http_status": 200,
    "meta": { ... PageMeta-shape ... },
    "sections": [{ heading, level, paragraphs, links, images, ctas }],
    "links": [absolute in-scope URLs discovered on the page],
    "image_urls": [absolute asset URLs],
    "dom": { ... DomNode shape (capped depth) ... },
    "compact_styles": {
        sampled,
        colors, background_colors, fills, strokes, border_colors,
        font_families, font_sizes, font_weights, line_heights, letter_spacings,
        paddings, margins, gaps, radii, shadows, transitions, breakpoints,
    }
  }

Writes:
  raw/pages/<slug>/rendered.html         (synthetic, from sections + links)
  raw/pages/<slug>/source.html           (same)
  raw/pages/<slug>/meta.json
  raw/pages/<slug>/computed-styles.json  (synthetic — list of pseudo-elements)
  raw/pages/<slug>/compact-styles.json   (the original aggregated stats)
  raw/pages/<slug>/dom-tree.json
  raw/pages/<slug>/a11y-tree.json
  raw/pages/<slug>/network-log.json
  raw/pages/<slug>/url.txt
  raw/captures.partial.jsonl             (one entry per page)
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime
from pathlib import Path

# Import from siblings if available
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.save_capture import slug_for, synth_rendered_html, save_skipped  # noqa: E402


# Properties that match what analyze_dna.extract_* functions read.
# We expand each compact entry back into an element-like record so the
# existing analyzer can consume it without modification.

def expand_compact_to_elements(compact: dict) -> list[dict]:
    """Convert the compact aggregated stats into a flat list of pseudo
    elements that `analyze_dna` can use for color/typography/spacing/etc.

    Each unique (color, fontFamily, fontSize, ...) combination becomes one
    element repeated according to the frequency cap so totals match.
    """
    if not compact:
        return []

    # Cap any single style's repetition to avoid explosions on extreme outliers.
    REPEAT_CAP = 200

    def emit_for_prop(map_obj: dict, prop_name: str, out: list[dict]) -> None:
        if not map_obj:
            return
        for value, freq in map_obj.items():
            n = min(int(freq), REPEAT_CAP)
            for _ in range(n):
                out.append({
                    "tag": "synthetic",
                    "classes": [],
                    "id": None,
                    "role": None,
                    "path": f"synthetic[{prop_name}]",
                    # analyze_dna.extract_typography skips elements with no
                    # text. We give every synthetic element a placeholder so
                    # font-family / font-size / line-height frequencies are
                    # counted. The placeholder never appears in any user-
                    # facing output.
                    "text": "x",
                    "styles": {prop_name: value},
                    "bbox": {"x": 0, "y": 0, "w": 0, "h": 0},
                })

    out: list[dict] = []
    emit_for_prop(compact.get("colors") or {}, "color", out)
    emit_for_prop(compact.get("background_colors") or {}, "background-color", out)
    emit_for_prop(compact.get("fills") or {}, "fill", out)
    emit_for_prop(compact.get("strokes") or {}, "stroke", out)
    emit_for_prop(compact.get("border_colors") or {}, "border-color", out)
    emit_for_prop(compact.get("font_families") or {}, "font-family", out)
    emit_for_prop(compact.get("font_sizes") or {}, "font-size", out)
    emit_for_prop(compact.get("font_weights") or {}, "font-weight", out)
    emit_for_prop(compact.get("line_heights") or {}, "line-height", out)
    emit_for_prop(compact.get("letter_spacings") or {}, "letter-spacing", out)
    emit_for_prop(compact.get("paddings") or {}, "padding", out)
    emit_for_prop(compact.get("margins") or {}, "margin", out)
    emit_for_prop(compact.get("gaps") or {}, "gap", out)
    emit_for_prop(compact.get("radii") or {}, "border-radius", out)
    emit_for_prop(compact.get("shadows") or {}, "box-shadow", out)
    emit_for_prop(compact.get("transitions") or {}, "transition", out)

    # Inject elements that have ALL the brand-color/brand-font signatures, so
    # the analyzer can correctly attribute brand colors to elements that also
    # have the brand font. This helps the component pattern detector etc.
    fonts = compact.get("font_families") or {}
    sizes = compact.get("font_sizes") or {}
    colors = compact.get("colors") or {}
    if fonts and sizes and colors:
        top_font = next(iter(fonts.keys()))
        top_size = next(iter(sizes.keys()))
        top_color = next(iter(colors.keys()))
        out.append({
            "tag": "synthetic-text",
            "classes": [],
            "id": None,
            "role": None,
            "path": "synthetic-text-combo",
            "text": "",
            "styles": {
                "color": top_color,
                "font-family": top_font,
                "font-size": top_size,
            },
            "bbox": {"x": 0, "y": 0, "w": 0, "h": 0},
        })

    return out


def save(payload: dict, out_dir: Path) -> dict:
    url = payload.get("url") or ""
    if not url:
        raise SystemExit("payload missing 'url'")
    slug = payload.get("slug") or slug_for(url)
    final_url = payload.get("final_url") or url

    page_dir = out_dir / "raw" / "pages" / slug
    page_dir.mkdir(parents=True, exist_ok=True)

    meta = payload.get("meta") or {"url": url, "final_url": final_url, "title": ""}
    if "url" not in meta:
        meta["url"] = url
    if "final_url" not in meta:
        meta["final_url"] = final_url

    sections = payload.get("sections") or []
    links = payload.get("links") or []
    image_urls = payload.get("image_urls") or []
    dom = payload.get("dom") or {"tag": "body", "children": []}
    compact = payload.get("compact_styles") or {}
    network = payload.get("network") or []

    elements = expand_compact_to_elements(compact)

    # Prefer real captured HTML when available; fall back to synthetic.
    real_html = payload.get("rendered_html")
    if real_html and isinstance(real_html, str) and len(real_html) > 1000:
        (page_dir / "rendered.html").write_text(real_html, encoding="utf-8")
        (page_dir / "source.html").write_text(real_html, encoding="utf-8")
    else:
        rendered = synth_rendered_html(slug, meta, sections, links)
        (page_dir / "rendered.html").write_text(rendered, encoding="utf-8")
        (page_dir / "source.html").write_text(rendered, encoding="utf-8")
    (page_dir / "url.txt").write_text(url, encoding="utf-8")
    (page_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (page_dir / "compact-styles.json").write_text(json.dumps(compact, indent=2), encoding="utf-8")
    (page_dir / "computed-styles.json").write_text(json.dumps({
        "page_slug": slug,
        "captured_at": datetime.utcnow().isoformat(),
        "elements": elements,
    }, indent=2), encoding="utf-8")
    (page_dir / "dom-tree.json").write_text(json.dumps({"root": dom}, indent=2), encoding="utf-8")
    (page_dir / "a11y-tree.json").write_text(json.dumps({"root": None}, indent=2), encoding="utf-8")
    (page_dir / "network-log.json").write_text(json.dumps({
        "page_slug": slug, "entries": network,
    }, indent=2), encoding="utf-8")

    if payload.get("screenshot_b64"):
        try:
            (page_dir / "screenshot.desktop.png").write_bytes(
                base64.b64decode(payload["screenshot_b64"])
            )
        except Exception:
            pass

    captures_log = out_dir / "raw" / "captures.partial.jsonl"
    captures_log.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "url": url,
        "slug": slug,
        "status": "ok",
        "duration_ms": int(payload.get("duration_ms") or 0),
        "http_status": int(payload.get("http_status") or 200),
        "final_url": final_url,
        "links": links,
        "image_urls": image_urls,
        "captured_at": datetime.utcnow().isoformat(),
    }
    with open(captures_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return {
        "slug": slug,
        "page_dir": str(page_dir),
        "elements_synthetic": len(elements),
        "links": len(links),
        "sections": len(sections),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--file", help="JSON payload file (defaults to stdin)")
    ap.add_argument("--skip-url", help="Record a skipped_purchase_url entry without capturing")
    ap.add_argument("--skip-reason", default="purchase URL")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_url:
        res = save_skipped(args.skip_url, args.skip_reason, out_dir)
        print(json.dumps(res))
        return

    raw = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    payload = json.loads(raw)
    res = save(payload, out_dir)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
