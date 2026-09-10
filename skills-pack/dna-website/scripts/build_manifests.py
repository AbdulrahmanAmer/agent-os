"""
Build captures.json + routes.json + asset_manifest.json from the per-page
artifacts already on disk (raw/pages/<slug>/* and raw/captures.partial.jsonl).

Used by the Chrome-MCP-driven crawl path; the Playwright pipeline writes these
manifests inline in scripts/crawl.py + scripts/download_assets.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from scripts.models import (
    Asset,
    AssetManifest,
    AssetStats,
    Capture,
    CaptureFiles,
    CaptureManifest,
    Route,
    RouteList,
    Viewport,
    write_model,
)


CAT_BY_EXT = {
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image",
    ".webp": "image", ".avif": "image", ".svg": "icon", ".ico": "icon",
    ".woff": "font", ".woff2": "font", ".ttf": "font", ".otf": "font",
    ".mp4": "video", ".webm": "video", ".mov": "video",
    ".css": "stylesheet", ".js": "script", ".mjs": "script",
}


def build_captures(out_dir: Path) -> CaptureManifest:
    pages_dir = out_dir / "raw" / "pages"
    captures: list[Capture] = []
    for page_dir in sorted(pages_dir.iterdir() if pages_dir.exists() else []):
        if not page_dir.is_dir():
            continue
        slug = page_dir.name
        url_file = page_dir / "url.txt"
        url = url_file.read_text(encoding="utf-8").strip() if url_file.exists() else ""
        files = CaptureFiles(
            source_html=f"raw/pages/{slug}/source.html",
            rendered_html=f"raw/pages/{slug}/rendered.html",
            screenshot_desktop=f"raw/pages/{slug}/screenshot.desktop.png",
            computed_styles=f"raw/pages/{slug}/computed-styles.json",
            dom_tree=f"raw/pages/{slug}/dom-tree.json",
            a11y_tree=f"raw/pages/{slug}/a11y-tree.json",
            network_log=f"raw/pages/{slug}/network-log.json",
            meta=f"raw/pages/{slug}/meta.json",
        )
        # Pull final_url from meta.json if available
        meta_path = page_dir / "meta.json"
        final_url = url
        if meta_path.exists():
            try:
                m = json.loads(meta_path.read_text(encoding="utf-8"))
                final_url = m.get("final_url") or url
            except Exception:
                pass
        captures.append(Capture(
            url=url,
            slug=slug,
            status="ok",
            duration_ms=0,
            http_status=200,
            final_url=final_url,
            files=files,
            viewport=Viewport(width=1440, height=900),
        ))

    # Pick up explicit skip entries from the captures.partial.jsonl
    partial = out_dir / "raw" / "captures.partial.jsonl"
    if partial.exists():
        seen_slugs = {c.slug for c in captures}
        for line in partial.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("status") == "skipped_purchase_url" and e.get("slug") not in seen_slugs:
                captures.append(Capture(
                    url=e.get("url") or "",
                    slug=e.get("slug") or "",
                    status="skipped_purchase_url",
                    error_message=e.get("reason") or "purchase URL",
                    duration_ms=0,
                    http_status=0,
                    final_url=e.get("final_url"),
                    files=CaptureFiles(
                        source_html="", rendered_html="",
                        screenshot_desktop="", computed_styles="",
                        dom_tree="", a11y_tree="", network_log="", meta="",
                    ),
                    viewport=Viewport(width=1440, height=900),
                ))
                seen_slugs.add(e.get("slug"))

    return CaptureManifest(
        total=len(captures),
        successful=sum(1 for c in captures if c.status == "ok"),
        failed=sum(1 for c in captures if c.status == "error"),
        captures=captures,
    )


def build_routes(captures: CaptureManifest, base_origin: str) -> RouteList:
    routes: list[Route] = []
    for cap in captures.captures:
        routes.append(Route(
            url=cap.url,
            slug=cap.slug,
            depth=0 if cap.url.rstrip("/") == base_origin.rstrip("/") else 1,
            source="crawl",
            discovered_at=datetime.utcnow(),
        ))
    return RouteList(base_origin=base_origin, routes=routes)


def build_asset_manifest(out_dir: Path, captures: CaptureManifest) -> AssetManifest:
    """Walk every meta.json + content-inventory and collect referenced
    image/CSS URLs. We don't actually download here — this just records what
    each page references."""
    assets: list[Asset] = []
    seen_urls: set[str] = set()

    def category_for(url: str) -> str:
        ext = ""
        path = urlparse(url).path
        if "." in path:
            ext = "." + path.rsplit(".", 1)[-1].lower().split("?")[0]
        return CAT_BY_EXT.get(ext, "image")

    pages_dir = out_dir / "raw" / "pages"
    inbox_dir = out_dir / "_inbox"

    for cap in captures.captures:
        if cap.status != "ok":
            continue
        inbox_file = inbox_dir / f"{cap.slug}.json"
        if not inbox_file.exists():
            continue
        try:
            data = json.loads(inbox_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for u in data.get("image_urls") or []:
            if u in seen_urls or not u.startswith(("http://", "https://")):
                continue
            seen_urls.add(u)
            cat = category_for(u)
            assets.append(Asset(
                original_url=u,
                local_path="",  # not downloaded
                content_hash=hashlib.sha256(u.encode()).hexdigest()[:16],
                content_type=mimetypes.guess_type(u)[0] or "application/octet-stream",
                size_bytes=0,
                type=cat,
                used_on_pages=[cap.slug],
                download_status="skipped",
                failure_reason="not downloaded — Chrome MCP path",
            ))
        # Also collect <img> src from sections
        for sec in data.get("sections") or []:
            for img in sec.get("images") or []:
                src = img.get("src") or ""
                if not src or src in seen_urls or not src.startswith(("http://", "https://")):
                    continue
                seen_urls.add(src)
                assets.append(Asset(
                    original_url=src,
                    local_path="",
                    content_hash=hashlib.sha256(src.encode()).hexdigest()[:16],
                    content_type=mimetypes.guess_type(src)[0] or "image/webp",
                    size_bytes=0,
                    type="image",
                    used_on_pages=[cap.slug],
                    download_status="skipped",
                    failure_reason="not downloaded — Chrome MCP path",
                ))

    # De-duplicate used_on_pages
    by_url: dict[str, Asset] = {}
    for a in assets:
        if a.original_url in by_url:
            existing = by_url[a.original_url]
            for p in a.used_on_pages:
                if p not in existing.used_on_pages:
                    existing.used_on_pages.append(p)
        else:
            by_url[a.original_url] = a
    deduped = list(by_url.values())

    counts: dict[str, int] = {}
    for a in deduped:
        counts[a.type] = counts.get(a.type, 0) + 1

    stats = AssetStats(
        total=len(deduped),
        by_type=counts,
        total_bytes=0,
        failed=0,
        skipped_oversized=0,
    )
    return AssetManifest(
        assets=deduped,
        by_url={a.original_url: a.local_path for a in deduped},
        stats=stats,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-origin", default="https://kindskiptracing.com")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    captures = build_captures(out_dir)
    routes = build_routes(captures, args.base_origin)
    assets = build_asset_manifest(out_dir, captures)

    write_model(out_dir / "captures.json", captures)
    write_model(out_dir / "routes.json", routes)
    write_model(out_dir / "asset_manifest.json", assets)

    print(f"captures: total={captures.total} ok={captures.successful} "
          f"failed={captures.failed} skipped="
          f"{sum(1 for c in captures.captures if c.status == 'skipped_purchase_url')}")
    print(f"routes:   {len(routes.routes)}")
    print(f"assets:   {assets.stats.total} unique URLs across pages "
          f"({assets.stats.by_type})")


if __name__ == "__main__":
    main()
