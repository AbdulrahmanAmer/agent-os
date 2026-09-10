"""
Route discovery. Combines multiple signals to find every URL worth crawling:

  1. /sitemap.xml  + any nested sitemaps
  2. /robots.txt   (Disallow paths often reveal interesting URLs)
  3. BFS crawl     from the seed URL, following same-origin links
  4. SPA sniff     by hooking pushState/replaceState in a headed browser

Writes routes.json (RouteList model).
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from scripts.config import Config
from scripts.models import Route, RouteList, write_model
from scripts.utils import (
    is_purchase_url,
    is_same_origin,
    is_same_registrable_domain,
    normalize_url,
    url_to_slug,
)


log = logging.getLogger(__name__)


# Skip these path patterns during BFS (binary assets, common irrelevant dirs)
SKIP_PATTERNS = [
    re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|tar|gz|mp4|mp3|woff2?|ttf|eot|css|js)(\?|$)", re.I),
    re.compile(r"/(static|assets|build|dist)/", re.I),
    re.compile(r"#"),
    re.compile(r"^mailto:|^tel:|^javascript:", re.I),
]


async def find_routes(config: Config, session_path: Path | None = None) -> RouteList:
    """Run all discovery strategies in parallel and merge results.

    Full-capture semantics: when config.max_pages == 0, no cap is applied at
    the discovery stage. Same for config.depth == 0 (BFS runs without depth
    limit). Purchase URLs are filtered out unconditionally.

    Discovery sources:
      - /sitemap.xml + nested <sitemapindex> children
      - /robots.txt Disallow paths (often reveal admin/feed URLs)
      - RSS/Atom feeds at common paths (/feed, /rss, /atom.xml, /blog/feed)
      - BFS link follow from the seed URL
      - SPA route sniff (pushState hook + framework artifacts)
    """
    discovered: dict[str, Route] = {}
    base = config.base_origin

    sitemap_urls, robots_urls, feed_urls = await asyncio.gather(
        _from_sitemap(base),
        _from_robots(base),
        _from_feeds(base),
    )
    for u in sitemap_urls:
        _add(discovered, u, depth=0, source="sitemap")
    for u in robots_urls:
        _add(discovered, u, depth=0, source="robots-disallow")
    for u in feed_urls:
        _add(discovered, u, depth=0, source="sitemap")  # treat feed-discovered URLs as sitemap-like

    bfs_urls = await _bfs_crawl(
        config.url, config,
        max_pages=config.max_pages,
        max_depth=config.depth,
        session_path=session_path,
    )
    for u, depth in bfs_urls:
        _add(discovered, u, depth=depth, source="crawl")

    spa_urls = await _sniff_spa_routes(config.url, config, session_path)
    for u in spa_urls:
        _add(discovered, u, depth=0, source="spa-sniff")

    # Filter to in-scope, then drop purchase URLs (defense in depth — BFS already
    # skips them, but sitemap/robots/SPA-sniff didn't pass through that filter).
    routes = list(discovered.values())
    routes = [r for r in routes if _in_scope(r.url, config)]

    purchase_skipped: list[Route] = [r for r in routes if is_purchase_url(r.url)]
    if purchase_skipped:
        log.warning(f"discover: filtered {len(purchase_skipped)} purchase URL(s)")
        for r in purchase_skipped:
            log.info(f"  skipped (purchase): {r.url}")
    routes = [r for r in routes if not is_purchase_url(r.url)]

    routes.sort(key=lambda r: (r.depth, r.url))

    # max_pages == 0 means "no cap" (full capture). Otherwise apply the cap.
    if config.max_pages and config.max_pages > 0:
        routes = routes[: config.max_pages]

    out = RouteList(base_origin=base, routes=routes)
    write_model(config.output_dir / "routes.json", out)
    log.info(f"Discovered {len(routes)} in-scope routes (purchase filter dropped {len(purchase_skipped)})")
    return out


def _add(d: dict[str, Route], url: str, depth: int, source: str) -> None:
    u = normalize_url(url)
    if u not in d:
        d[u] = Route(
            url=u,
            slug=url_to_slug(u),
            depth=depth,
            source=source,
            discovered_at=datetime.utcnow(),
        )


def _in_scope(url: str, config: Config) -> bool:
    if config.include_subdomains:
        return is_same_registrable_domain(url, config.url)
    return is_same_origin(url, config.url)


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------

async def _from_sitemap(base_origin: str) -> list[str]:
    """Recursively walk sitemap.xml + nested sitemap indexes."""
    urls: list[str] = []
    queue = [urljoin(base_origin, "/sitemap.xml")]
    visited: set[str] = set()

    async with aiohttp.ClientSession() as session:
        while queue:
            sm_url = queue.pop()
            if sm_url in visited:
                continue
            visited.add(sm_url)
            try:
                async with session.get(sm_url, timeout=10) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
            except Exception:
                continue
            try:
                root = ET.fromstring(text)
            except ET.ParseError:
                continue
            ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            # Sitemap index?
            for sm in root.findall(f"{ns}sitemap"):
                loc = sm.find(f"{ns}loc")
                if loc is not None and loc.text:
                    queue.append(loc.text.strip())
            for url in root.findall(f"{ns}url"):
                loc = url.find(f"{ns}loc")
                if loc is not None and loc.text:
                    urls.append(loc.text.strip())
    return urls


async def _from_feeds(base_origin: str) -> list[str]:
    """Probe common RSS/Atom feed paths and extract <link>/<loc>/<id> URLs.

    Sites built on WordPress, Ghost, Duda, Jekyll, Hugo, Substack, etc. all
    expose feeds at one of these conventional paths. Pulling links from
    feeds catches blog posts that aren't linked from the homepage (and so
    would be invisible to BFS).
    """
    candidates = [
        "/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml",
        "/feed/atom", "/feed/rss", "/feed/rss2", "/feed.xml",
        "/blog/feed", "/blog/feed/", "/blog/rss", "/blog/atom.xml",
        "/news/feed", "/articles/feed", "/posts/feed",
    ]
    found: list[str] = []
    headers = {"User-Agent": "DNA-website/0.1 (+research)", "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml"}
    async with aiohttp.ClientSession(headers=headers) as session:
        for path in candidates:
            url = urljoin(base_origin, path)
            try:
                async with session.get(url, timeout=8, allow_redirects=True) as resp:
                    if resp.status != 200:
                        continue
                    ctype = (resp.headers.get("content-type") or "").lower()
                    if not any(k in ctype for k in ("xml", "rss", "atom")):
                        continue
                    text = await resp.text(errors="ignore")
            except Exception:
                continue
            # Try to parse as XML
            try:
                root = ET.fromstring(text)
            except ET.ParseError:
                continue
            # RSS: <item><link>URL</link>; Atom: <entry><link href="URL"/>
            for el in root.iter():
                tag = el.tag.split("}", 1)[-1] if "}" in el.tag else el.tag
                if tag == "link":
                    href = el.get("href")
                    if href:
                        found.append(href.strip())
                    elif el.text:
                        found.append(el.text.strip())
                elif tag in ("loc", "id"):
                    if el.text:
                        found.append(el.text.strip())
    # De-dupe + same-origin filter happens at the caller
    return list(set(u for u in found if u.startswith(("http://", "https://"))))


async def _from_robots(base_origin: str) -> list[str]:
    """Pull URLs from Disallow rules in robots.txt. Often reveals admin pages."""
    robots_url = urljoin(base_origin, "/robots.txt")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(robots_url, timeout=10) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text()
    except Exception:
        return []
    paths: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("disallow:"):
            p = line.split(":", 1)[1].strip()
            if p and p != "/":
                paths.append(urljoin(base_origin, p))
    return paths


# ---------------------------------------------------------------------------
# BFS crawl
# ---------------------------------------------------------------------------

async def _bfs_crawl(
    seed: str,
    config: Config,
    *,
    max_pages: int,
    max_depth: int,
    session_path: Path | None = None,
) -> list[tuple[str, int]]:
    """Plain HTML BFS. Fast — no JS rendering. Use playwright for SPA sniffing only.

    Unlimited semantics:
      max_pages == 0 → no cap on number of pages explored
      max_depth == 0 → no cap on BFS depth
    Purchase URLs are skipped completely (never enqueued, never visited).
    """
    visited: set[str] = set()
    out: list[tuple[str, int]] = []
    queue = deque([(normalize_url(seed), 0)])

    # Treat 0 as "unlimited" (interpreted as a very large number internally)
    pages_unlimited = (max_pages is None) or (max_pages <= 0)
    depth_unlimited = (max_depth is None) or (max_depth <= 0)
    effective_max_pages = float("inf") if pages_unlimited else max_pages
    effective_max_depth = float("inf") if depth_unlimited else max_depth

    headers = {"User-Agent": "DNA-website/0.1 (+research)"}
    cookies = _cookies_from_session(session_path) if session_path else None

    sem = asyncio.Semaphore(5)

    async with aiohttp.ClientSession(headers=headers, cookies=cookies) as session:
        while queue and len(out) < effective_max_pages:
            url, depth = queue.popleft()
            if url in visited or depth > effective_max_depth:
                continue
            if is_purchase_url(url):
                log.info(f"bfs: skipped purchase URL {url}")
                continue
            visited.add(url)
            out.append((url, depth))

            async with sem:
                try:
                    async with session.get(url, timeout=15, allow_redirects=True) as resp:
                        if "text/html" not in (resp.headers.get("content-type") or ""):
                            continue
                        html = await resp.text(errors="ignore")
                except Exception:
                    continue

            for link in _extract_links(html, url):
                norm = normalize_url(link)
                if norm in visited:
                    continue
                if not _in_scope(norm, config):
                    continue
                if any(p.search(norm) for p in SKIP_PATTERNS):
                    continue
                if is_purchase_url(norm):
                    # Never enqueue a purchase URL.
                    continue
                queue.append((norm, depth + 1))

    return out


def _cookies_from_session(session_path: Path) -> dict[str, str]:
    """Convert Playwright storage_state cookies into a flat dict for aiohttp.

    session_path may be either:
      - storage_state.json file → read directly
      - user-data-dir → look for a sibling storage_state.json
    """
    import json
    p = Path(session_path)
    if p.is_dir():
        # Look for a sibling storage_state.json (auth.login writes one).
        candidate = p.parent / "storage_state.json"
        if not candidate.exists():
            return {}
        p = candidate
    try:
        data = json.loads(p.read_text())
        return {c["name"]: c["value"] for c in data.get("cookies", [])}
    except Exception:
        return {}


def _extract_links(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(p.search(href) for p in SKIP_PATTERNS):
            continue
        absolute = urljoin(base, href)
        if absolute.startswith(("http://", "https://")):
            out.append(absolute)
    return out


# ---------------------------------------------------------------------------
# SPA route sniffing
# ---------------------------------------------------------------------------

async def _sniff_spa_routes(
    seed: str, config: Config, session_path: Path | None = None
) -> list[str]:
    """
    Load the seed in a real browser, hook pushState/replaceState, and watch
    for client-side route changes. Also scans framework artifacts.

    session_path may be a directory (persistent user-data-dir) or a JSON file
    (storage_state). For fingerprint-binding sites the directory variant is
    required for the page to render its authenticated state.
    """
    script = (Path(__file__).parent.parent / "browser_scripts" / "extract_spa_routes.js").read_text()
    found: set[str] = set()

    use_persistent = bool(
        session_path and Path(session_path).exists() and Path(session_path).is_dir()
    )

    async with async_playwright() as p:
        if use_persistent:
            # Force headed mode — same fingerprint as login. See auth.py.
            ctx = await p.chromium.launch_persistent_context(
                str(session_path),
                headless=False,
                viewport={"width": 1440, "height": 900},
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            browser = None
        else:
            browser = await p.chromium.launch(headless=not config.headed)
            kwargs = {"storage_state": str(session_path)} if session_path else {}
            ctx = await browser.new_context(**kwargs)
            page = await ctx.new_page()
        try:
            await page.goto(seed, wait_until="domcontentloaded", timeout=30_000)
            await page.add_init_script(script)
            # Give the page 5s to surface routes
            await asyncio.sleep(5)
            sniffed = await page.evaluate("() => window.__DNA_SPA_ROUTES || []")
            for u in sniffed:
                absolute = urljoin(seed, u)
                if _in_scope(absolute, config):
                    found.add(normalize_url(absolute))
        except Exception as e:
            log.warning(f"SPA sniff failed: {e}")
        finally:
            if browser is not None:
                await browser.close()
            else:
                await ctx.close()
    return list(found)
