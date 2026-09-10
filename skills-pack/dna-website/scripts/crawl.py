"""
Per-page capture stage. For each route:
  - opens the URL in Playwright
  - waits for network idle / timeout
  - saves source.html (pre-JS) and rendered.html (post-JS)
  - takes desktop + optional mobile screenshots
  - injects browser_scripts/extract_computed_styles.js to dump element styles
  - logs network activity (sanitized)
  - extracts metadata (title, og, json-ld, canonical, etc.)
  - extracts accessibility tree

Writes:
  raw/pages/<slug>/* — one directory per page
  captures.json      — CaptureManifest with all results
  manifest.partial.json — incremental progress for --resume

Concurrency: N browser contexts run in parallel (config.concurrency). Each
context is fully isolated (cookies/state copied from session_path if set).
Rate limit: config.rate_limit requests/second globally enforced via a token
bucket shared across contexts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import (
    BrowserContext,
    Page,
    Request,
    Response,
    Route,
    async_playwright,
)

from scripts.config import Config
from scripts.models import (
    A11yTree,
    Capture,
    CaptureFiles,
    CaptureManifest,
    ComputedStylesDoc,
    DomTree,
    NetworkLog,
    PageMeta,
    RouteList,
    Viewport,
    write_model,
)
from scripts.utils import (
    ensure_dir,
    extract_json_shape,
    is_purchase_url,
    relative_to_output,
    sanitize_network_log,
)


log = logging.getLogger(__name__)


DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
MOBILE_VIEWPORT = {"width": 390, "height": 844}

# Default per-page hard timeout in seconds
PAGE_TIMEOUT = 45


async def capture_all(
    config: Config,
    routes: RouteList,
    session_path: Path | None,
) -> CaptureManifest:
    """Crawl every route. Writes per-page artifacts + captures.json.

    session_path here may be either:
      - A directory (the persistent user-data-dir from auth.login) — preferred,
        keeps the browser fingerprint stable.
      - A storage_state.json file (legacy / unauthenticated runs).
      - None (no auth).
    """
    pages_dir = ensure_dir(config.output_dir / "raw" / "pages")

    # Detect whether session_path is a user-data-dir or a storage_state file.
    use_persistent = bool(
        session_path
        and Path(session_path).exists()
        and Path(session_path).is_dir()
    )

    # Resume: load completed slugs (and previously-recorded captures) from
    # manifest.partial.json so captures.json comes out complete after resume.
    completed_slugs: set[str] = set()
    prior_captures: list[Capture] = []
    partial_path = config.output_dir / "manifest.partial.json"
    if config.resume and partial_path.exists():
        try:
            data = json.loads(partial_path.read_text())
            completed_slugs = set(data.get("completed_slugs", []))
            for raw_cap in data.get("captures", []):
                try:
                    prior_captures.append(Capture.model_validate(raw_cap))
                except Exception as e:
                    log.warning(f"Resume: dropping malformed capture: {e}")
            log.info(
                f"Resume: skipping {len(completed_slugs)} previously completed pages "
                f"({len(prior_captures)} prior captures restored)"
            )
        except Exception as e:
            log.warning(f"Could not read partial manifest: {e}")

    # Build the worklist
    work = [r for r in routes.routes if r.slug not in completed_slugs]

    # Token bucket rate limiter shared across all contexts
    rate_lock = asyncio.Lock()
    last_request = [0.0]
    interval = 1.0 / max(config.rate_limit, 0.1)

    async def wait_for_token():
        async with rate_lock:
            now = time.monotonic()
            wait = max(0.0, last_request[0] + interval - now)
            if wait:
                await asyncio.sleep(wait)
            last_request[0] = time.monotonic()

    # Spawn N browser contexts. Start with the prior_captures so captures.json
    # comes out complete on resume.
    captures: list[Capture] = list(prior_captures)
    sem = asyncio.Semaphore(config.concurrency)

    async with async_playwright() as p:
        # When using a persistent user-data-dir, we cannot have concurrent
        # contexts pointing at the same directory. Drop concurrency to 1 so
        # the same browser fingerprint is preserved across the run.
        #
        # Critical: force headed=False (i.e. headless=False). Sites that
        # fingerprint the browser see headless as a distinct device. We need
        # bit-for-bit the same fingerprint as the login session.
        if use_persistent:
            persistent_ctx = await p.chromium.launch_persistent_context(
                str(session_path),
                headless=False,
                viewport=DESKTOP_VIEWPORT,
            )
            # Close any blank tabs Playwright pre-opens — we'll create per-page.
            for pg in list(persistent_ctx.pages)[1:]:
                try:
                    await pg.close()
                except Exception:
                    pass
            browser = None
            log.info("crawl: using persistent user-data-dir; effective concurrency = 1")
        else:
            persistent_ctx = None
            browser = await p.chromium.launch(headless=not config.headed)

        async def capture_one(route_obj):
            # Hard rule: never navigate a purchase URL. Defense in depth — discover
            # already filtered, but we re-check at navigation time anyway.
            if is_purchase_url(route_obj.url):
                log.warning(f"crawl: skipping purchase URL {route_obj.url}")
                captures.append(_skipped_purchase_capture(route_obj.url, route_obj.slug))
                _write_partial(config, completed_slugs | {route_obj.slug}, captures)
                completed_slugs.add(route_obj.slug)
                return

            async with sem:
                await wait_for_token()
                if persistent_ctx is not None:
                    # Reuse the same persistent context — fingerprint stable.
                    try:
                        capture = await _capture_page(
                            persistent_ctx, route_obj.url, route_obj.slug, pages_dir,
                            config, output_dir=config.output_dir,
                        )
                        captures.append(capture)
                        _write_partial(config, completed_slugs | {route_obj.slug}, captures)
                        completed_slugs.add(route_obj.slug)
                    except Exception as e:
                        log.error(f"Capture failed for {route_obj.url}: {e}")
                        captures.append(_failed_capture(route_obj.url, route_obj.slug, str(e)))
                        _write_partial(config, completed_slugs | {route_obj.slug}, captures)
                        completed_slugs.add(route_obj.slug)
                else:
                    kwargs: dict[str, Any] = {"viewport": DESKTOP_VIEWPORT}
                    if session_path and not use_persistent:
                        kwargs["storage_state"] = str(session_path)
                    ctx = await browser.new_context(**kwargs)
                    try:
                        capture = await _capture_page(
                            ctx, route_obj.url, route_obj.slug, pages_dir,
                            config, output_dir=config.output_dir,
                        )
                        captures.append(capture)
                        _write_partial(config, completed_slugs | {route_obj.slug}, captures)
                        completed_slugs.add(route_obj.slug)
                    except Exception as e:
                        log.error(f"Capture failed for {route_obj.url}: {e}")
                        captures.append(_failed_capture(route_obj.url, route_obj.slug, str(e)))
                        _write_partial(config, completed_slugs | {route_obj.slug}, captures)
                        completed_slugs.add(route_obj.slug)
                    finally:
                        await ctx.close()

        if persistent_ctx is not None:
            # Sequential — the persistent context can't safely be hammered in
            # parallel (and the fingerprint must stay stable).
            for r in work:
                await capture_one(r)
            await persistent_ctx.close()
        else:
            await asyncio.gather(*[capture_one(r) for r in work])
            await browser.close()

    manifest = CaptureManifest(
        total=len(captures),
        successful=sum(1 for c in captures if c.status == "ok"),
        failed=sum(1 for c in captures if c.status == "error"),
        captures=captures,
    )
    write_model(config.output_dir / "captures.json", manifest)

    # Clean up partial manifest if everything succeeded
    if manifest.failed == 0 and partial_path.exists():
        partial_path.unlink()

    return manifest


def _write_partial(
    config: Config,
    completed: set[str],
    captures: list[Capture] | None = None,
) -> None:
    """Write manifest.partial.json with completed slugs and (optionally) the
    full capture list-so-far. Written after every page so --resume can pick up
    cleanly after any interruption.
    """
    path = config.output_dir / "manifest.partial.json"
    payload: dict[str, Any] = {
        "started_at": config.started_at.isoformat(),
        "completed_slugs": sorted(completed),
    }
    if captures is not None:
        payload["captures"] = [json.loads(c.model_dump_json()) for c in captures]
    path.write_text(json.dumps(payload, indent=2))


def _failed_capture(url: str, slug: str, error: str) -> Capture:
    return Capture(
        url=url,
        slug=slug,
        status="error",
        error_message=error,
        duration_ms=0,
        http_status=0,
        files=CaptureFiles(
            source_html="", rendered_html="",
            screenshot_desktop="", computed_styles="",
            dom_tree="", a11y_tree="", network_log="", meta="",
        ),
        viewport=Viewport(**DESKTOP_VIEWPORT),
    )


def _skipped_purchase_capture(url: str, slug: str) -> Capture:
    """A Capture entry that records we deliberately did not navigate."""
    return Capture(
        url=url,
        slug=slug,
        status="skipped_purchase_url",
        error_message="Skipped: matches purchase URL pattern",
        duration_ms=0,
        http_status=0,
        final_url=url,
        files=CaptureFiles(
            source_html="", rendered_html="",
            screenshot_desktop="", computed_styles="",
            dom_tree="", a11y_tree="", network_log="", meta="",
        ),
        viewport=Viewport(**DESKTOP_VIEWPORT),
    )


# ---------------------------------------------------------------------------
# Per-page work
# ---------------------------------------------------------------------------

async def _capture_page(
    ctx: BrowserContext,
    url: str,
    slug: str,
    pages_dir: Path,
    config: Config,
    *,
    output_dir: Path,
) -> Capture:
    """Capture everything for a single page."""
    page_dir = ensure_dir(pages_dir / slug)
    started = time.time()

    # Set up network capture before navigating
    net_entries: list[dict] = []
    _attach_network_listeners(ctx, net_entries)

    page = await ctx.new_page()
    page.set_default_timeout(PAGE_TIMEOUT * 1000)

    # Save source HTML by intercepting the document response
    source_html_holder = {"html": ""}

    async def grab_source(response: Response):
        if response.url == url or response.url == url + "/":
            try:
                source_html_holder["html"] = await response.text()
            except Exception:
                pass

    page.on("response", grab_source)

    # Navigate
    try:
        resp = await page.goto(url, wait_until="networkidle", timeout=PAGE_TIMEOUT * 1000)
    except Exception:
        # Fall back to domcontentloaded
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT * 1000)
        await asyncio.sleep(3)

    http_status = resp.status if resp else 0
    final_url = page.url

    # Best-effort scroll for lazy-loaded content
    try:
        scroll_script = (Path(__file__).parent.parent / "browser_scripts" / "infinite_scroll.js").read_text()
        await page.evaluate(scroll_script)
    except Exception:
        pass

    # 1. Source HTML (pre-render)
    (page_dir / "source.html").write_text(source_html_holder["html"] or "", encoding="utf-8")

    # 2. Rendered HTML
    rendered = await page.content()
    (page_dir / "rendered.html").write_text(rendered, encoding="utf-8")

    # 3. Screenshots
    screenshot_desktop = page_dir / "screenshot.desktop.png"
    await page.screenshot(path=str(screenshot_desktop), full_page=True)
    screenshot_mobile_path = None
    if config.mobile_also:
        screenshot_mobile_path = page_dir / "screenshot.mobile.png"
        await page.set_viewport_size(MOBILE_VIEWPORT)
        await asyncio.sleep(1)
        await page.screenshot(path=str(screenshot_mobile_path), full_page=True)
        await page.set_viewport_size(DESKTOP_VIEWPORT)

    # 4. Computed styles via injected script
    styles_script = (Path(__file__).parent.parent / "browser_scripts" / "extract_computed_styles.js").read_text()
    raw_styles = await page.evaluate(styles_script)
    styles_doc = ComputedStylesDoc(
        page_slug=slug,
        captured_at=datetime.utcnow(),
        elements=raw_styles,   # already in ElementStyles shape
    )
    write_model(page_dir / "computed-styles.json", styles_doc)

    # 5. DOM tree
    dom = await page.evaluate("""() => {
      const walk = (el) => ({
        tag: el.tagName ? el.tagName.toLowerCase() : null,
        id: el.id || null,
        classes: el.className && el.className.split ? el.className.split(/\\s+/).filter(Boolean) : [],
        role: el.getAttribute ? el.getAttribute('role') : null,
        children: [...(el.children || [])].slice(0, 64).map(walk),
      });
      return walk(document.body);
    }""")
    write_model(page_dir / "dom-tree.json", DomTree(root=dom))

    # 6. Accessibility tree
    try:
        a11y_root = await page.accessibility.snapshot()
        write_model(page_dir / "a11y-tree.json", A11yTree(root=a11y_root))
    except Exception:
        write_model(page_dir / "a11y-tree.json", A11yTree(root=None))

    # 7. Metadata
    meta = _extract_meta(rendered, url, final_url)
    write_model(page_dir / "meta.json", meta)

    # 8. Network log (sanitized)
    sanitized = sanitize_network_log(net_entries)
    write_model(
        page_dir / "network-log.json",
        NetworkLog(page_slug=slug, entries=sanitized),
    )

    duration_ms = int((time.time() - started) * 1000)
    await page.close()

    return Capture(
        url=url,
        slug=slug,
        status="ok",
        duration_ms=duration_ms,
        http_status=http_status,
        redirected_to=final_url if final_url != url else None,
        final_url=final_url,
        files=CaptureFiles(
            source_html=relative_to_output(page_dir / "source.html", output_dir),
            rendered_html=relative_to_output(page_dir / "rendered.html", output_dir),
            screenshot_desktop=relative_to_output(screenshot_desktop, output_dir),
            screenshot_mobile=(
                relative_to_output(screenshot_mobile_path, output_dir)
                if screenshot_mobile_path else None
            ),
            computed_styles=relative_to_output(page_dir / "computed-styles.json", output_dir),
            dom_tree=relative_to_output(page_dir / "dom-tree.json", output_dir),
            a11y_tree=relative_to_output(page_dir / "a11y-tree.json", output_dir),
            network_log=relative_to_output(page_dir / "network-log.json", output_dir),
            meta=relative_to_output(page_dir / "meta.json", output_dir),
        ),
        viewport=Viewport(**DESKTOP_VIEWPORT),
    )


# ---------------------------------------------------------------------------
# Network listener
# ---------------------------------------------------------------------------

def _attach_network_listeners(ctx: BrowserContext, entries: list[dict]) -> None:
    """Attach request/response listeners on the context that append to entries."""
    in_flight: dict[str, dict] = {}

    def on_request(req: Request):
        in_flight[req.url + "|" + req.method] = {
            "url": req.url,
            "method": req.method,
            "resource_type": req.resource_type,
            "request_headers": dict(req.headers),
            "started_at": time.monotonic(),
        }
        # Best-effort body shape
        try:
            body = req.post_data
            if body:
                try:
                    body_json = json.loads(body)
                    in_flight[req.url + "|" + req.method]["request_body_shape"] = extract_json_shape(body_json)
                except Exception:
                    pass
        except Exception:
            pass

    async def on_response(resp: Response):
        key = resp.url + "|" + resp.request.method
        entry = in_flight.pop(key, None) or {
            "url": resp.url, "method": resp.request.method,
            "resource_type": resp.request.resource_type,
            "request_headers": dict(resp.request.headers),
        }
        entry["status"] = resp.status
        entry["response_headers"] = dict(resp.headers)
        entry["duration_ms"] = int((time.monotonic() - entry.pop("started_at", time.monotonic())) * 1000)
        ctype = resp.headers.get("content-type", "")
        # Body shape for JSON only, and only if small
        if "application/json" in ctype:
            try:
                body = await resp.json()
                entry["response_body_shape"] = extract_json_shape(body)
            except Exception:
                pass
        try:
            body_bytes = await resp.body()
            entry["response_size"] = len(body_bytes)
        except Exception:
            entry["response_size"] = 0
        entries.append(entry)

    ctx.on("request", on_request)
    ctx.on("response", lambda r: asyncio.create_task(on_response(r)))


# ---------------------------------------------------------------------------
# Meta extraction
# ---------------------------------------------------------------------------

def _extract_meta(html: str, original_url: str, final_url: str) -> PageMeta:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string if soup.title and soup.title.string else "").strip()

    def meta_content(selectors: list[tuple[str, str]]) -> str | None:
        for attr, val in selectors:
            tag = soup.find("meta", attrs={attr: val})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    description = meta_content([("name", "description"), ("property", "description")])
    canonical_tag = soup.find("link", rel="canonical")
    canonical = canonical_tag["href"].strip() if canonical_tag and canonical_tag.get("href") else None

    og: dict[str, str] = {}
    twitter: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        prop = tag.get("property") or tag.get("name") or ""
        content = tag.get("content")
        if not content:
            continue
        if prop.startswith("og:"):
            og[prop[3:]] = content
        elif prop.startswith("twitter:"):
            twitter[prop[8:]] = content

    json_ld = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            json_ld.append(json.loads(s.string or "{}"))
        except Exception:
            pass

    html_tag = soup.find("html")
    lang = html_tag.get("lang") if html_tag else None
    viewport_tag = soup.find("meta", attrs={"name": "viewport"})
    viewport = viewport_tag.get("content") if viewport_tag else None
    favicon_tag = soup.find("link", rel=re.compile("icon", re.I))
    favicon = favicon_tag.get("href") if favicon_tag else None
    manifest_tag = soup.find("link", rel="manifest")
    manifest_url = manifest_tag.get("href") if manifest_tag else None

    return PageMeta(
        url=original_url,
        final_url=final_url,
        title=title,
        description=description,
        canonical=canonical,
        og=og,
        twitter=twitter,
        json_ld=json_ld,
        lang=lang,
        viewport=viewport,
        favicon=favicon,
        manifest_url=manifest_url,
    )
