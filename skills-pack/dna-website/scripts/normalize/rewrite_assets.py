"""
Deterministic asset URL → local path rewriter.

Reads the dna-website asset_manifest.json + (when available) the v1
asset directory, copies bytes into the real-project's assets/ tree,
returns a URL→local map that the HTML rewriter consumes.

Output layout:
  real-project/
  ├── assets/
  │   ├── images/<hash>.<ext>
  │   ├── icons/<hash>.<ext>
  │   ├── fonts/<hash>.<ext>
  │   ├── videos/<hash>.<ext>
  │   ├── stylesheets/<hash>.css
  │   └── scripts/<hash>.js  (only KEPT if listed in --keep-scripts;
  │                            framework runtime is dropped by default)

Asset rewriting policy:
  - Same-origin assets: copied locally, URL → relative path.
  - kindskiptracing.com / known same-host CDN: copied locally.
  - Cross-origin (third-party CDN, Google Fonts etc): preserved as-is —
    the rebuilt site keeps fetching them at runtime (the alternative is
    downloading + hosting Google Fonts which raises licensing questions).
  - Analytics / tracker hosts: stripped entirely from the rewrite map so
    references in HTML simply break (a noscript-equivalent cleanup).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import tldextract


ANALYTICS_HOSTS = {
    "google-analytics.com", "googletagmanager.com", "connect.facebook.net",
    "hotjar.com", "clarity.ms", "doubleclick.net", "segment.io",
    "mixpanel.com", "amplitude.com", "fullstory.com", "matomo.org",
    "googleadservices.com",
}


@dataclass
class RewriteResult:
    url_to_local: dict[str, str] = field(default_factory=dict)
    assets_copied: int = 0
    bytes_copied: int = 0
    cross_origin_kept: list[str] = field(default_factory=list)
    analytics_stripped: list[str] = field(default_factory=list)
    missing_local: list[str] = field(default_factory=list)


def copy_assets(
    capture_dir: Path,
    real_project_dir: Path,
    asset_manifest: dict,
    source_host: str,
) -> RewriteResult:
    """Copy every downloaded asset into the real-project tree and produce
    a URL→local-path map.
    """
    result = RewriteResult()
    target_root = real_project_dir / "assets"
    for sub in ("images", "icons", "fonts", "videos", "stylesheets", "scripts"):
        (target_root / sub).mkdir(parents=True, exist_ok=True)

    type_to_dir = {
        "image": "images", "icon": "icons", "font": "fonts",
        "video": "videos", "stylesheet": "stylesheets", "script": "scripts",
    }

    source_netloc = urlparse(source_host).netloc
    src_ext = tldextract.extract(source_netloc)
    src_registrable = f"{src_ext.domain}.{src_ext.suffix}" if src_ext.suffix else source_netloc

    def _same_registrable(asset_netloc: str) -> bool:
        ext = tldextract.extract(asset_netloc)
        registrable = f"{ext.domain}.{ext.suffix}" if ext.suffix else asset_netloc
        return registrable == src_registrable

    for asset in (asset_manifest.get("assets") or []):
        original_url = asset.get("original_url") or ""
        if not original_url:
            continue

        netloc = urlparse(original_url).netloc
        # Strip analytics URLs entirely
        if any(netloc.endswith(h) for h in ANALYTICS_HOSTS):
            result.analytics_stripped.append(original_url)
            continue

        # Keep cross-origin (different registrable domain) URLs as-is
        if netloc and not _same_registrable(netloc):
            result.cross_origin_kept.append(original_url)
            # Map URL to itself so HTML rewrite leaves it alone
            result.url_to_local[original_url] = original_url
            continue

        local_path = asset.get("local_path") or ""
        if not local_path:
            result.missing_local.append(original_url)
            continue

        src = capture_dir / local_path
        if not src.exists():
            result.missing_local.append(original_url)
            continue

        # Determine target subdir from asset type
        sub = type_to_dir.get(asset.get("type", "image"), "images")
        # Keep the original filename (which is <hash>.<ext>)
        name = Path(local_path).name
        dst = target_root / sub / name
        if not dst.exists():
            try:
                shutil.copy2(src, dst)
                result.assets_copied += 1
                result.bytes_copied += dst.stat().st_size
            except Exception:
                result.missing_local.append(original_url)
                continue
        rel_path = f"assets/{sub}/{name}"
        result.url_to_local[original_url] = rel_path

    return result


def rewrite_urls_inside_css(real_project_dir: Path, result: RewriteResult, base_origin: str) -> int:
    """Walk every copied .css file and rewrite url(...) references to local
    paths. @font-face/url() inside CSS doesn't get caught by the HTML
    rewriter because the CSS lives in a separate file."""
    import re as _re
    base_host = urlparse(base_origin).netloc.lower()
    css_dir = real_project_dir / "assets" / "stylesheets"
    if not css_dir.exists():
        return 0

    # Build the same expanded lookup the HTML rewriter uses
    expanded: dict[str, str] = {}
    for absolute, local in result.url_to_local.items():
        if local == absolute:
            continue
        expanded[absolute] = local
        try:
            p = urlparse(absolute)
        except Exception:
            continue
        if p.netloc.lower() != base_host or not p.path:
            continue
        expanded[p.path] = local
        if p.path.startswith("/"):
            expanded[p.path[1:]] = local
        if "/" in p.path:
            bare = p.path.rsplit("/", 1)[-1]
            expanded.setdefault(bare, local)

    rewrites = 0

    def _lookup(raw: str) -> str | None:
        s = (raw or "").strip().strip("'\"")
        if not s:
            return None
        bare = s.split("?", 1)[0].split("#", 1)[0]
        for cand in (s, bare):
            if cand in expanded:
                return expanded[cand]
            if not cand.startswith("/") and "/" + cand in expanded:
                return expanded["/" + cand]
        return None

    url_re = _re.compile(r'url\(\s*([\'"]?)([^\'")\s]+?)\1\s*\)')

    for css_file in sorted(css_dir.glob("*.css")):
        try:
            text = css_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        new_text, _local_rewrites = url_re.subn(
            lambda m: _sub_css_url(m, _lookup, expanded, css_file.name),
            text,
        )
        if new_text != text:
            css_file.write_text(new_text, encoding="utf-8")
            rewrites += _local_rewrites
    return rewrites


def _sub_css_url(m, lookup, expanded, css_name: str) -> str:
    q, val = m.group(1), m.group(2)
    if val.startswith("data:"):
        return m.group(0)
    local = lookup(val)
    if local:
        # CSS files live at assets/stylesheets/<hash>.css. Targets like
        # assets/fonts/<hash>.woff2 need to become ../fonts/<hash>.woff2.
        if local.startswith("assets/"):
            local = "../" + local[len("assets/"):]
        return f'url("{local}")'
    return m.group(0)


def write_asset_index(real_project_dir: Path, result: RewriteResult) -> None:
    """Drop an assets.json manifest into the project so downstream tools
    (and the operator) can see what got copied."""
    out = {
        "url_to_local": result.url_to_local,
        "stats": {
            "copied": result.assets_copied,
            "bytes": result.bytes_copied,
            "cross_origin_kept": len(result.cross_origin_kept),
            "analytics_stripped": len(result.analytics_stripped),
            "missing_local": len(result.missing_local),
        },
        "cross_origin_kept": result.cross_origin_kept[:50],
        "analytics_stripped": result.analytics_stripped,
        "missing_local": result.missing_local[:50],
    }
    (real_project_dir / "assets.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    """Drop an assets.json manifest into the project so downstream tools
    (and the operator) can see what got copied."""
    out = {
        "url_to_local": result.url_to_local,
        "stats": {
            "copied": result.assets_copied,
            "bytes": result.bytes_copied,
            "cross_origin_kept": len(result.cross_origin_kept),
            "analytics_stripped": len(result.analytics_stripped),
            "missing_local": len(result.missing_local),
        },
        "cross_origin_kept": result.cross_origin_kept[:50],
        "analytics_stripped": result.analytics_stripped,
        "missing_local": result.missing_local[:50],
    }
    (real_project_dir / "assets.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
