"""
Take a JSON page-capture payload on stdin and write the per-page artifacts
to outputs/<run>/raw/pages/<slug>/* in the dna-website layout.

Used when the captures arrive from outside the Python pipeline — e.g. via
the Claude in Chrome MCP extension, which returns structured JSON rather
than raw HTML.

Input JSON shape:
  {
    "url":  "https://kindskiptracing.com/...",
    "slug": "home",                 # optional; derived from url if missing
    "final_url": "...",             # optional
    "http_status": 200,             # optional
    "duration_ms": 0,               # optional
    "meta": {... PageMeta-shaped ...},
    "elements": [{ tag, classes, id, role, path, text, styles, bbox }, ...],
    "dom": {...DomNode...},
    "sections": [{ heading, level, paragraphs, links, images, ctas }],
    "links": [...],                 # in-scope URLs discovered on the page
    "image_urls": [...],            # absolute asset URLs
  }

CLI:
  python -m scripts.save_capture --out <output_dir>

If the JSON payload contains 'screenshot_b64' (base64-encoded PNG bytes)
the screenshot is decoded and saved alongside.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


def slug_for(url: str) -> str:
    p = urlparse(url)
    path = (p.path or "/").strip("/")
    parts = path.split("/") if path else []
    if p.query:
        q = "_".join(f"{k}-{v}" for k, v in
                     sorted(x.split("=", 1) if "=" in x else (x, "")
                            for x in p.query.split("&") if x))
        parts.append(q)
    if not parts:
        return "home"
    slug = "__".join(parts).lower()
    out = []
    for c in slug:
        if c.isalnum() or c in "-_":
            out.append(c)
        else:
            out.append("-")
    return "".join(out) or "home"


def synth_rendered_html(slug: str, meta: dict, sections: list, links: list) -> str:
    """Build a minimal HTML document from structured data so that
    BeautifulSoup-based analyzers (analyze_content) have something to chew on.

    This is NOT the original page HTML — it's a structurally-correct
    reconstruction that captures the content inventory without any embedded
    cookies/tokens/scripts.
    """
    import html as html_lib

    parts = [
        "<!DOCTYPE html>",
        f"<html lang=\"{html_lib.escape(meta.get('lang') or 'en')}\">",
        "<head>",
        f"<title>{html_lib.escape(meta.get('title') or '')}</title>",
    ]
    desc = meta.get("description")
    if desc:
        parts.append(f'<meta name="description" content="{html_lib.escape(desc)}">')
    canon = meta.get("canonical")
    if canon:
        parts.append(f'<link rel="canonical" href="{html_lib.escape(canon)}">')
    favicon = meta.get("favicon")
    if favicon:
        parts.append(f'<link rel="icon" href="{html_lib.escape(favicon)}">')
    parts.append("</head>")
    parts.append("<body>")
    parts.append(f'<header data-slug="{html_lib.escape(slug)}"></header>')

    for sec in (sections or []):
        parts.append("<section>")
        h_text = sec.get("heading")
        h_level = sec.get("level") or 2
        if h_text:
            parts.append(f"<h{h_level}>{html_lib.escape(h_text)}</h{h_level}>")
        for para in (sec.get("paragraphs") or []):
            parts.append(f"<p>{html_lib.escape(para)}</p>")
        for img in (sec.get("images") or []):
            src = img.get("src") or ""
            alt = img.get("alt") or ""
            parts.append(f'<img src="{html_lib.escape(src)}" alt="{html_lib.escape(alt)}">')
        for cta in (sec.get("ctas") or []):
            text = cta.get("text") or ""
            href = cta.get("href")
            if cta.get("kind") == "button":
                parts.append(f'<button>{html_lib.escape(text)}</button>')
            else:
                parts.append(f'<a href="{html_lib.escape(href or "#")}">{html_lib.escape(text)}</a>')
        for link in (sec.get("links") or []):
            text = link.get("text") or ""
            href = link.get("href") or "#"
            parts.append(f'<a href="{html_lib.escape(href)}">{html_lib.escape(text)}</a>')
        parts.append("</section>")

    # Fallback: dump remaining outbound links into a nav so BFS sees them
    parts.append("<nav data-role=\"outbound\">")
    for u in links or []:
        parts.append(f'<a href="{html_lib.escape(u)}">{html_lib.escape(u)}</a>')
    parts.append("</nav>")

    parts.append("</body></html>")
    return "\n".join(parts)


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

    elements = payload.get("elements") or []
    dom = payload.get("dom") or {"tag": "body", "children": []}
    sections = payload.get("sections") or []
    links = payload.get("links") or []
    image_urls = payload.get("image_urls") or []
    network = payload.get("network") or []

    rendered = synth_rendered_html(slug, meta, sections, links)
    (page_dir / "rendered.html").write_text(rendered, encoding="utf-8")
    (page_dir / "source.html").write_text(rendered, encoding="utf-8")
    (page_dir / "url.txt").write_text(url, encoding="utf-8")
    (page_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (page_dir / "computed-styles.json").write_text(json.dumps({
        "page_slug": slug,
        "captured_at": datetime.utcnow().isoformat(),
        "elements": elements,
    }, indent=2), encoding="utf-8")
    (page_dir / "dom-tree.json").write_text(json.dumps({"root": dom}, indent=2), encoding="utf-8")
    (page_dir / "a11y-tree.json").write_text(json.dumps({"root": None}, indent=2), encoding="utf-8")
    (page_dir / "network-log.json").write_text(json.dumps({
        "page_slug": slug,
        "entries": network,
    }, indent=2), encoding="utf-8")

    if payload.get("screenshot_b64"):
        try:
            (page_dir / "screenshot.desktop.png").write_bytes(
                base64.b64decode(payload["screenshot_b64"])
            )
        except Exception:
            pass

    # Append to running captures log so we can rebuild captures.json later
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
    return {"slug": slug, "page_dir": str(page_dir), "elements": len(elements), "links": len(links)}


def save_skipped(url: str, reason: str, out_dir: Path) -> dict:
    slug = slug_for(url)
    captures_log = out_dir / "raw" / "captures.partial.jsonl"
    captures_log.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "url": url,
        "slug": slug,
        "status": "skipped_purchase_url",
        "duration_ms": 0,
        "http_status": 0,
        "final_url": url,
        "links": [],
        "image_urls": [],
        "captured_at": datetime.utcnow().isoformat(),
        "reason": reason,
    }
    with open(captures_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return {"slug": slug, "status": "skipped_purchase_url"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="Output directory (e.g. outputs/kindskiptracing-2026-05-11)")
    ap.add_argument("--file", help="Read JSON payload from this file instead of stdin")
    ap.add_argument("--skip-url", help="Record a skipped_purchase_url entry for this URL without capturing")
    ap.add_argument("--skip-reason", default="purchase URL", help="Reason text for --skip-url")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_url:
        res = save_skipped(args.skip_url, args.skip_reason, out_dir)
        print(json.dumps(res))
        return

    if args.file:
        raw = Path(args.file).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    payload = json.loads(raw)
    res = save(payload, out_dir)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
