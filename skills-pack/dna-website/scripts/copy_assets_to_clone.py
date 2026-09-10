"""
Helper: copy capture/raw/assets/* into a clean kindskiptracing-clone tree
with HUMAN-READABLE filenames so a designer/rebrand-er can find them.

Reads the captured asset_manifest.json (which has the original CDN URLs)
and copies each asset under a friendly name derived from its URL path —
e.g. `https://kindskiptracing.com/assets/img/about-us/josh.avif` becomes
`public/images/about-us-josh.avif`.

Fonts get short names (urbanist-regular.woff2 etc.) that match what
base.css already references.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse


CAPTURE = Path("outputs/kindskiptracing-2026-05-11")
CLONE = Path("clones/kindskiptracing-clone")


def friendly_image_name(url: str, content_hash: str, ext: str) -> str:
    p = urlparse(url).path
    # Strip leading /, drop the leading "assets/img/" if present
    p = p.lstrip("/")
    p = re.sub(r"^assets/(?:img|images)/", "", p)
    # Collapse path separators into hyphens
    p = re.sub(r"[/\\]+", "-", p)
    # Strip the original extension off; we'll add the canonical one
    p = re.sub(r"\.[A-Za-z0-9]+$", "", p)
    p = re.sub(r"[^A-Za-z0-9._-]+", "-", p).strip("-").lower()
    if not p:
        p = f"image-{content_hash[:8]}"
    return f"{p}{ext}"


def friendly_font_name(url: str, ext: str) -> str:
    # e.g. /assets/fonts/Urbanist-Bold.woff2 → urbanist-bold.woff2
    name = Path(urlparse(url).path).stem.lower()
    name = re.sub(r"[^a-z0-9-]+", "-", name).strip("-")
    return f"{name}{ext}"


def main() -> int:
    manifest_path = CAPTURE / "asset_manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: {manifest_path} not found", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    img_dir = CLONE / "public" / "images"
    font_dir = CLONE / "public" / "fonts"
    icon_dir = CLONE / "public" / "icons"
    css_dir = CLONE / "public" / "stylesheets"
    for d in (img_dir, font_dir, icon_dir, css_dir):
        d.mkdir(parents=True, exist_ok=True)

    url_to_clean: dict[str, str] = {}
    counts = {"image": 0, "font": 0, "icon": 0, "stylesheet": 0, "script": 0, "skipped": 0}

    for asset in manifest.get("assets", []):
        local = asset.get("local_path") or ""
        if not local:
            counts["skipped"] += 1
            continue
        src = CAPTURE / local
        if not src.exists():
            counts["skipped"] += 1
            continue
        url = asset.get("original_url") or ""
        atype = asset.get("type") or "image"
        ext = Path(local).suffix
        # We don't ship the captured JS bundles — they're Angular runtime.
        if atype == "script":
            counts["skipped"] += 1
            continue
        if atype == "font":
            name = friendly_font_name(url, ext)
            dst = font_dir / name
        elif atype == "icon":
            name = friendly_image_name(url, asset.get("content_hash", ""), ext)
            dst = icon_dir / name
        elif atype == "stylesheet":
            # Preserve original-ish name; if anonymous, hash it
            stem = Path(urlparse(url).path).stem
            if not stem:
                stem = "styles-" + asset.get("content_hash", "")[:8]
            dst = css_dir / f"{stem.lower()}.css"
            name = dst.name
        else:  # image
            name = friendly_image_name(url, asset.get("content_hash", ""), ext)
            dst = img_dir / name
        if dst.exists():
            counts[atype] = counts.get(atype, 0) + 1
            url_to_clean[url] = f"public/{dst.parent.name}/{dst.name}"
            continue
        try:
            shutil.copy2(src, dst)
            counts[atype] = counts.get(atype, 0) + 1
            url_to_clean[url] = f"public/{dst.parent.name}/{dst.name}"
        except Exception as e:
            print(f"WARN copy failed: {url} → {dst}: {e}", file=sys.stderr)
            counts["skipped"] += 1

    # Emit a friendly URL map for the page-builder agents
    (CLONE / "asset-map.json").write_text(
        json.dumps(url_to_clean, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print("Asset copy summary:")
    for k, v in sorted(counts.items()):
        print(f"  {k:12}  {v}")
    print(f"Map written to {CLONE / 'asset-map.json'} ({len(url_to_clean)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
