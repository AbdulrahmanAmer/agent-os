"""
Asset download stage.

Collects every asset URL from captured pages (HTML + CSS + manifests), then
downloads them in two phases:
  Phase 1: plain aiohttp with the session cookies — fast.
  Phase 2: failures retry via Playwright with the imported storage_state —
           handles edge cases like auth-gated CDNs and Cloudflare-protected
           assets.

Dedupes by content hash. Categorizes by content type. Writes asset_manifest.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from scripts.config import Config
from scripts.models import (
    Asset,
    AssetManifest,
    AssetStats,
    CaptureManifest,
    write_model,
)
from scripts.utils import (
    content_hash,
    ensure_dir,
    is_purchase_url,
    is_same_origin,
    normalize_url,
    relative_to_output,
)


log = logging.getLogger(__name__)


CATEGORY_BY_EXT: dict[str, str] = {
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image",
    ".webp": "image", ".avif": "image", ".bmp": "image",
    ".svg": "icon",   # treat svg as icon by default; refined by size below
    ".ico": "icon",
    ".woff": "font", ".woff2": "font", ".ttf": "font", ".otf": "font", ".eot": "font",
    ".mp4": "video", ".webm": "video", ".mov": "video",
    ".css": "stylesheet",
    ".js": "script", ".mjs": "script",
}


async def fetch_all(
    config: Config,
    captures: CaptureManifest,
    session_path: Path | None,
) -> AssetManifest:
    """Collect, download, and manifest every asset."""
    assets_root = ensure_dir(config.output_dir / "raw" / "assets")
    for cat in ("images", "fonts", "icons", "videos", "stylesheets", "scripts"):
        ensure_dir(assets_root / cat)

    # Phase A: collect URLs
    url_to_pages: dict[str, set[str]] = {}
    for cap in captures.captures:
        if cap.status != "ok":
            continue
        rendered = (config.output_dir / cap.files.rendered_html).read_text(errors="ignore")
        for u in _extract_asset_urls(rendered, cap.url):
            if is_purchase_url(u):
                # Never fetch a purchase URL as an asset, even if a page
                # referenced one in a link or background.
                continue
            url_to_pages.setdefault(normalize_url(u), set()).add(cap.slug)

    # Also process CSS files we've discovered to find @font-face srcs + url() refs
    extra_from_css: dict[str, set[str]] = {}
    for u in list(url_to_pages.keys()):
        if u.endswith(".css") or "css" in (urlparse(u).path):
            # Will be fetched and re-parsed in phase B
            pass

    log.info(f"Collected {len(url_to_pages)} unique asset URLs")

    # Phase B: download
    max_bytes = config.max_asset_size_mb * 1024 * 1024
    cookies = _cookies_from_session(session_path) if session_path else None

    assets: list[Asset] = []
    failed: list[tuple[str, str]] = []   # (url, reason)
    seen_hashes: set[str] = set()
    sem = asyncio.Semaphore(10)
    rate_lock = asyncio.Lock()
    last_request = [0.0]
    interval = 1.0 / max(config.rate_limit, 0.1)

    async with aiohttp.ClientSession(cookies=cookies) as session:
        async def fetch_one(url: str):
            async with rate_lock:
                wait = max(0.0, last_request[0] + interval - time.monotonic())
                if wait:
                    await asyncio.sleep(wait)
                last_request[0] = time.monotonic()
            async with sem:
                try:
                    async with session.get(url, timeout=30, allow_redirects=True) as resp:
                        if resp.status >= 400:
                            failed.append((url, f"HTTP {resp.status}"))
                            return
                        body = await resp.read()
                        ctype = resp.headers.get("content-type", "")
                except Exception as e:
                    failed.append((url, str(e)))
                    return

                if len(body) > max_bytes:
                    assets.append(_skip_asset(url, len(body), assets_root, config))
                    return

                _save_asset(url, body, ctype, assets, seen_hashes, assets_root, config, url_to_pages.get(url, set()))

                # If it's CSS, parse it for more URLs and recurse
                if "css" in ctype or url.endswith(".css"):
                    new_urls = _extract_urls_from_css(body.decode(errors="ignore"), url)
                    for nu in new_urls:
                        n_norm = normalize_url(nu)
                        if n_norm not in url_to_pages:
                            url_to_pages[n_norm] = set()
                            await fetch_one(n_norm)

        await asyncio.gather(*(fetch_one(u) for u in list(url_to_pages.keys())))

    # Phase C: retry failures via Playwright
    if failed:
        log.info(f"Phase 2: retrying {len(failed)} failed assets via headed browser")
        await _retry_via_playwright(
            failed, session_path, assets, seen_hashes, assets_root, config, url_to_pages
        )

    # Build manifest
    by_url = {a.original_url: a.local_path for a in assets}
    stats = AssetStats(
        total=len(assets),
        by_type=_count_by_type(assets),
        total_bytes=sum(a.size_bytes for a in assets if a.download_status == "ok"),
        failed=sum(1 for a in assets if a.download_status == "failed"),
        skipped_oversized=sum(1 for a in assets if a.download_status == "skipped"),
    )
    manifest = AssetManifest(assets=assets, by_url=by_url, stats=stats)
    write_model(config.output_dir / "asset_manifest.json", manifest)
    return manifest


# ---------------------------------------------------------------------------
# URL extraction
# ---------------------------------------------------------------------------

def _extract_asset_urls(html: str, base_url: str) -> list[str]:
    """Pull every asset reference out of an HTML document."""
    out: list[str] = []
    soup = BeautifulSoup(html, "lxml")

    for img in soup.find_all("img"):
        if img.get("src"):
            out.append(urljoin(base_url, img["src"]))
        if img.get("srcset"):
            for part in img["srcset"].split(","):
                u = part.strip().split()[0]
                if u:
                    out.append(urljoin(base_url, u))

    for tag in soup.find_all(["script", "source", "video", "audio"]):
        if tag.get("src"):
            out.append(urljoin(base_url, tag["src"]))

    for link in soup.find_all("link"):
        if link.get("href"):
            rel = " ".join(link.get("rel") or [])
            if any(k in rel for k in ("stylesheet", "icon", "preload", "manifest")):
                out.append(urljoin(base_url, link["href"]))

    # Inline styles
    for el in soup.find_all(style=True):
        for u in _extract_urls_from_css(el["style"], base_url):
            out.append(u)

    # <style>...</style>
    for s in soup.find_all("style"):
        if s.string:
            for u in _extract_urls_from_css(s.string, base_url):
                out.append(u)

    return out


CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^)'\"]+)['\"]?\s*\)")


def _extract_urls_from_css(css: str, base_url: str) -> list[str]:
    return [urljoin(base_url, m) for m in CSS_URL_RE.findall(css) if not m.startswith("data:")]


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def _save_asset(
    url: str,
    body: bytes,
    content_type: str,
    assets: list[Asset],
    seen_hashes: set[str],
    assets_root: Path,
    config: Config,
    used_on_pages: set[str],
) -> None:
    h = content_hash(body)
    if h in seen_hashes:
        # Already on disk — still record the URL alias
        existing = next((a for a in assets if a.content_hash == h), None)
        if existing:
            existing.used_on_pages.extend(p for p in used_on_pages if p not in existing.used_on_pages)
        return
    seen_hashes.add(h)

    ext = _guess_ext(url, content_type)
    category = CATEGORY_BY_EXT.get(ext, "scripts" if "script" in content_type else "images")
    cat_dir = assets_root / _plural_category(category)
    out_path = cat_dir / f"{h}{ext}"
    out_path.write_bytes(body)

    assets.append(Asset(
        original_url=url,
        local_path=relative_to_output(out_path, config.output_dir),
        content_hash=h,
        content_type=content_type or mimetypes.guess_type(url)[0] or "application/octet-stream",
        size_bytes=len(body),
        type=category,
        used_on_pages=list(used_on_pages),
    ))


def _skip_asset(url: str, size: int, assets_root: Path, config: Config) -> Asset:
    return Asset(
        original_url=url,
        local_path="",
        content_hash="",
        content_type="",
        size_bytes=size,
        type="image",  # arbitrary
        used_on_pages=[],
        download_status="skipped",
        failure_reason=f"oversize ({size} > {config.max_asset_size_mb * 1024 * 1024})",
    )


def _guess_ext(url: str, content_type: str) -> str:
    path = urlparse(url).path
    if "." in path.rsplit("/", 1)[-1]:
        return "." + path.rsplit(".", 1)[-1].lower().split("?")[0]
    if content_type:
        guess = mimetypes.guess_extension(content_type.split(";")[0])
        if guess:
            return guess
    return ".bin"


def _plural_category(cat: str) -> str:
    return {
        "image": "images", "font": "fonts", "icon": "icons",
        "video": "videos", "stylesheet": "stylesheets", "script": "scripts",
    }[cat]


def _count_by_type(assets: list[Asset]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for a in assets:
        counts[a.type] = counts.get(a.type, 0) + 1
    return counts


def _cookies_from_session(session_path: Path) -> dict[str, str]:
    p = Path(session_path)
    if p.is_dir():
        candidate = p.parent / "storage_state.json"
        if not candidate.exists():
            return {}
        p = candidate
    try:
        data = json.loads(p.read_text())
        return {c["name"]: c["value"] for c in data.get("cookies", [])}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Playwright fallback for hostile assets
# ---------------------------------------------------------------------------

async def _retry_via_playwright(
    failed: list[tuple[str, str]],
    session_path: Path | None,
    assets: list[Asset],
    seen_hashes: set[str],
    assets_root: Path,
    config: Config,
    url_to_pages: dict[str, set[str]],
) -> None:
    """Re-fetch failed assets via Playwright with session imported."""
    use_persistent = bool(
        session_path and Path(session_path).exists() and Path(session_path).is_dir()
    )
    async with async_playwright() as p:
        if use_persistent:
            # Headed mode for fingerprint stability — see auth.py.
            ctx = await p.chromium.launch_persistent_context(
                str(session_path),
                headless=False,
                viewport={"width": 1440, "height": 900},
            )
            browser = None
        else:
            browser = await p.chromium.launch(headless=True)
            kwargs = {"storage_state": str(session_path)} if session_path else {}
            ctx = await browser.new_context(**kwargs)

        async def fetch(url: str):
            try:
                resp = await ctx.request.get(url, timeout=30000)
                if resp.status >= 400:
                    assets.append(Asset(
                        original_url=url, local_path="", content_hash="",
                        content_type="", size_bytes=0, type="image",
                        used_on_pages=[], download_status="failed",
                        failure_reason=f"HTTP {resp.status} (phase 2)",
                    ))
                    return
                body = await resp.body()
                _save_asset(
                    url, body, resp.headers.get("content-type", ""),
                    assets, seen_hashes, assets_root, config,
                    url_to_pages.get(url, set()),
                )
            except Exception as e:
                assets.append(Asset(
                    original_url=url, local_path="", content_hash="",
                    content_type="", size_bytes=0, type="image",
                    used_on_pages=[], download_status="failed",
                    failure_reason=f"{e} (phase 2)",
                ))

        await asyncio.gather(*(fetch(u) for u, _ in failed))
        if browser is not None:
            await browser.close()
        else:
            await ctx.close()
