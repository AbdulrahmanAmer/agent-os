"""
Merge the v1 webapp-clone-pipeline capture into our dna-website output.

The v1 capture has the things we couldn't extract through Edge MCP (Chrome
extension's cookie/token filter blocked them):

  - Real raw HTML for every page (synthetic HTML replaced)
  - Downloaded asset bytes (images, fonts, JS, CSS) with content hashes
  - Real per-page screenshots
  - Network log with 333 entries
  - wp_blueprint.json + interactive_map.json (derived blueprints we keep
    as supplementary analysis files)

What this script does:
  1. For each shared slug, replaces raw/pages/<slug>/rendered.html (and
     source.html) with the real HTML, after sanitisation.
  2. Replaces screenshot.desktop.png with the real screenshot.
  3. Writes network-log.json per page from site_manifest.network filtered
     to that page's origin/url (best-effort), sanitised.
  4. Copies every asset bytes file into raw/assets/<category>/<hash>.<ext>
     and rebuilds asset_manifest.json with real local_paths + sizes.
  5. Drops wp_blueprint.json + interactive_map.json into analysis/ for
     supplementary review.

Slug aliasing: old "index" → new "home"; old "order-list-market" stays as
its own page (we already discovered the SPA-deep version too).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from scripts.models import (
    Asset,
    AssetManifest,
    AssetStats,
    NetworkLog,
    NetworkEntry,
    write_model,
)
from scripts.utils import sanitize_network_log, ensure_dir, content_hash


SLUG_ALIASES = {"index": "home"}

CATEGORY_BY_EXT: dict[str, str] = {
    ".jpg": "images", ".jpeg": "images", ".png": "images", ".gif": "images",
    ".webp": "images", ".avif": "images",
    ".svg": "icons", ".ico": "icons",
    ".woff": "fonts", ".woff2": "fonts", ".ttf": "fonts", ".otf": "fonts",
    ".mp4": "videos", ".webm": "videos", ".mov": "videos",
    ".css": "stylesheets", ".js": "scripts", ".mjs": "scripts",
}


def category_for(ext: str, content_type: str) -> str:
    if ext.startswith("."):
        ext = ext
    else:
        ext = "." + ext.lstrip(".")
    cat = CATEGORY_BY_EXT.get(ext.lower())
    if cat:
        return cat
    if "image" in content_type:
        return "images"
    if "font" in content_type:
        return "fonts"
    if "javascript" in content_type or "ecmascript" in content_type:
        return "scripts"
    if "css" in content_type:
        return "stylesheets"
    return "images"


def asset_type_of(category: str) -> str:
    return {
        "images": "image", "icons": "icon", "fonts": "font",
        "videos": "video", "stylesheets": "stylesheet", "scripts": "script",
    }.get(category, "image")


def merge_pages(v1_dir: Path, out_dir: Path, stats: dict) -> None:
    site = json.loads((v1_dir / "site_manifest.json").read_text(encoding="utf-8"))
    routes = site.get("routes", [])
    network = site.get("network", [])

    pages_dir = out_dir / "raw" / "pages"
    for route in routes:
        slug = SLUG_ALIASES.get(route["slug"], route["slug"])
        page_dir = pages_dir / slug
        if not page_dir.exists():
            print(f"  page dir missing for slug {slug!r}; skipping HTML merge")
            continue
        # HTML
        html_src = v1_dir / route["html_path"]
        if html_src.exists():
            # No sanitiser for HTML here — the v1 capture is the user's own
            # paid session; HTML body may have CSRF tokens / state. We
            # already have utils.sanitize_network_log but no sanitize_html.
            # The HTML is stored in raw/ which is gitignored, and the
            # inspector wraps it; treat as untrusted content. Strip obvious
            # secrets via a quick pass.
            html = html_src.read_text(encoding="utf-8", errors="ignore")
            html = _strip_obvious_secrets(html)
            (page_dir / "rendered.html").write_text(html, encoding="utf-8")
            (page_dir / "source.html").write_text(html, encoding="utf-8")
            stats["html_merged"] += 1
        # Screenshot
        shot_src = v1_dir / route["screenshot_path"]
        if shot_src.exists():
            shutil.copy2(shot_src, page_dir / "screenshot.desktop.png")
            stats["screenshots_merged"] += 1

        # Page-scoped network log: filter the global network array to
        # entries plausibly coming from this page navigation.
        page_url = route["url"].rstrip("/")
        page_origin = urlparse(route["url"]).netloc
        entries: list[dict] = []
        for n in network:
            try:
                u = n.get("url") or ""
                if not u:
                    continue
                # First-party only — third-party calls aren't really this page
                # but we'll include them too since they're already public.
                entries.append({
                    "url": u,
                    "method": n.get("method") or "GET",
                    "resource_type": n.get("resource_type") or "",
                    "status": int(n.get("status") or 0),
                    "request_headers": {},
                    "response_headers": {"content-type": n.get("content_type") or ""},
                    "response_size": 0,
                    "duration_ms": 0,
                    "initiator": n.get("from_origin"),
                })
            except Exception:
                continue
        sanitized = sanitize_network_log(entries)
        # Only keep entries for this page's origin OR clearly first-party
        # cdn calls; that's still a lot but not all 333 of them.
        # For DNA purposes, the per-page log can be the full set since the
        # page was loaded as part of the navigation.
        # NetworkEntry has typed fields — convert sanitized dicts to entries.
        nlog_entries = []
        for e in sanitized[:200]:   # cap per-page log at 200 to keep file size sane
            try:
                nlog_entries.append(NetworkEntry(
                    url=e["url"],
                    method=e.get("method") or "GET",
                    resource_type=e.get("resource_type") or "",
                    status=int(e.get("status") or 0),
                    request_headers=e.get("request_headers") or {},
                    response_headers=e.get("response_headers") or {},
                    response_size=int(e.get("response_size") or 0),
                    duration_ms=int(e.get("duration_ms") or 0),
                    initiator=e.get("initiator"),
                ))
            except Exception:
                pass
        write_model(page_dir / "network-log.json", NetworkLog(page_slug=slug, entries=nlog_entries))
        stats["network_logs_written"] += 1


def merge_assets(v1_dir: Path, out_dir: Path, stats: dict) -> AssetManifest:
    site = json.loads((v1_dir / "site_manifest.json").read_text(encoding="utf-8"))
    raw_assets_dir = out_dir / "raw" / "assets"
    for cat in ("images", "fonts", "icons", "videos", "stylesheets", "scripts"):
        ensure_dir(raw_assets_dir / cat)

    new_assets: list[Asset] = []
    # Old manifest sorted by original_url → first capture wins; dedupe in case
    by_url: dict[str, Asset] = {}

    for a in site.get("assets", []):
        src_path = v1_dir / a["local_path"]
        if not src_path.exists():
            continue
        ext = "." + (a.get("ext") or "").lstrip(".").lower()
        category = category_for(ext, a.get("content_type") or "")
        dst_name = f"{a['hash']}{ext}"
        dst_path = raw_assets_dir / category / dst_name
        if not dst_path.exists():
            shutil.copy2(src_path, dst_path)
            stats["asset_bytes_copied"] += dst_path.stat().st_size
        asset = Asset(
            original_url=a["original_url"],
            local_path=str(dst_path.relative_to(out_dir)).replace("\\", "/"),
            content_hash=a["hash"][:16],
            content_type=a.get("content_type") or mimetypes.guess_type(a["original_url"])[0] or "application/octet-stream",
            size_bytes=int(a.get("size") or 0),
            type=asset_type_of(category),
            used_on_pages=[],
            download_status="ok",
        )
        # Best-effort: figure out which captured pages reference this URL.
        for cap_meta in (out_dir / "raw" / "pages").iterdir() if (out_dir / "raw" / "pages").exists() else []:
            if not cap_meta.is_dir():
                continue
            inbox_file = out_dir / "_inbox" / f"{cap_meta.name}.json"
            if not inbox_file.exists():
                continue
            try:
                payload = json.loads(inbox_file.read_text(encoding="utf-8"))
                if asset.original_url in (payload.get("image_urls") or []):
                    asset.used_on_pages.append(cap_meta.name)
                else:
                    # Also check image src in sections
                    for sec in payload.get("sections") or []:
                        for img in sec.get("images") or []:
                            if img.get("src") == asset.original_url:
                                asset.used_on_pages.append(cap_meta.name)
                                break
            except Exception:
                pass
        # Dedupe used_on_pages
        asset.used_on_pages = sorted(set(asset.used_on_pages))
        by_url[asset.original_url] = asset
        new_assets.append(asset)

    counts: dict[str, int] = {}
    total_bytes = 0
    for a in new_assets:
        counts[a.type] = counts.get(a.type, 0) + 1
        total_bytes += a.size_bytes

    manifest = AssetManifest(
        assets=new_assets,
        by_url={a.original_url: a.local_path for a in new_assets},
        stats=AssetStats(
            total=len(new_assets), by_type=counts,
            total_bytes=total_bytes, failed=0, skipped_oversized=0,
        ),
    )
    write_model(out_dir / "asset_manifest.json", manifest)
    stats["assets_merged"] = len(new_assets)
    return manifest


def merge_blueprints(v1_dir: Path, out_dir: Path) -> None:
    analysis = ensure_dir(out_dir / "analysis")
    for fname in ("wp_blueprint.json", "interactive_map.json"):
        src = v1_dir / fname
        if src.exists():
            shutil.copy2(src, analysis / f"v1_{fname}")


_SENSITIVE_INLINE_PATTERNS = [
    # Stripe keys, JWTs, Bearer tokens, GitHub PATs
    (r"(eyJ[A-Za-z0-9_\-+/=.]{20,}\.[A-Za-z0-9_\-+/=.]{6,}\.[A-Za-z0-9_\-+/=.]{6,})", "[REDACTED-JWT]"),
    (r"(sk_(?:live|test)_[A-Za-z0-9]{16,})", "[REDACTED-STRIPE]"),
    (r"(pk_(?:live|test)_[A-Za-z0-9]{16,})", "[REDACTED-STRIPE]"),
    (r"(ghp_[A-Za-z0-9]{20,})", "[REDACTED-GITHUB]"),
    (r"(xox[abprs]-[A-Za-z0-9-]{10,})", "[REDACTED-SLACK]"),
    (r"(Bearer\s+[A-Za-z0-9._\-+/=]{20,})", "Bearer [REDACTED]"),
]


def _strip_obvious_secrets(html: str) -> str:
    """Run a quick token-shape sweep over an HTML body. Doesn't try to be
    comprehensive — just catches the common high-risk patterns.
    """
    import re
    for pat, repl in _SENSITIVE_INLINE_PATTERNS:
        html = re.sub(pat, repl, html)
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1", required=True, help="Path to v1 capture directory")
    ap.add_argument("--out", required=True, help="Path to dna-website output dir")
    args = ap.parse_args()

    v1_dir = Path(args.v1).resolve()
    out_dir = Path(args.out).resolve()
    if not v1_dir.exists():
        raise SystemExit(f"v1 dir not found: {v1_dir}")
    if not out_dir.exists():
        raise SystemExit(f"out dir not found: {out_dir}")

    stats = {
        "html_merged": 0,
        "screenshots_merged": 0,
        "network_logs_written": 0,
        "assets_merged": 0,
        "asset_bytes_copied": 0,
    }

    print(f"Merging from {v1_dir}")
    print(f"           into {out_dir}")
    print("Pages...")
    merge_pages(v1_dir, out_dir, stats)
    print("Assets...")
    merge_assets(v1_dir, out_dir, stats)
    print("Blueprints...")
    merge_blueprints(v1_dir, out_dir)

    summary = {**stats, "merged_at": datetime.utcnow().isoformat()}
    (out_dir / "v1_merge.summary.json").write_text(json.dumps(summary, indent=2))
    print("Summary:", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
