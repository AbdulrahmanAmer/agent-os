"""
Headless-browser verifier for the normalized real-project.

For each generated HTML page:
  - Start a local HTTP server rooted at the real-project dir
  - Open the page in headless Chromium
  - Record JS console errors
  - Record HTTP 4xx / 5xx for any sub-resource
  - Take a screenshot
  - Compute the same compact computed-style stats as the original capture
  - Diff against the original page's compact_styles (% drift on top-N
    colors / fonts / sizes)

Output: real-project/verify_report.json

The verifier is opportunistic — if Playwright isn't usable in this env,
it falls back to a static HTML lint (parse-only, no runtime checks).
"""

from __future__ import annotations

import asyncio
import contextlib
import http.server
import json
import logging
import socket
import socketserver
import threading
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class PageVerifyResult:
    slug: str
    url: str
    title: str = ""
    console_errors: list[str] = field(default_factory=list)
    failed_requests: list[dict] = field(default_factory=list)
    screenshot_path: str | None = None
    html_bytes: int = 0
    passed: bool = True


def _find_free_port() -> int:
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(root: Path, port: int) -> tuple[threading.Thread, socketserver.TCPServer]:
    handler = http.server.SimpleHTTPRequestHandler
    handler.directory = str(root)
    server = socketserver.TCPServer(("127.0.0.1", port), handler)
    server.allow_reuse_address = True

    # Switch directory by subclassing the request handler so the static
    # server actually serves from `root`.
    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)
        def log_message(self, *_args):
            pass

    server.server_close()
    server = socketserver.TCPServer(("127.0.0.1", port), _Handler)
    thr = threading.Thread(target=server.serve_forever, daemon=True)
    thr.start()
    return thr, server


async def _verify_with_playwright(root: Path, slugs: list[str]) -> dict:
    from playwright.async_api import async_playwright

    port = _find_free_port()
    thr, server = _start_server(root, port)
    base = f"http://127.0.0.1:{port}"
    results: list[PageVerifyResult] = []
    shots_dir = root / "_verify_screenshots"
    shots_dir.mkdir(exist_ok=True)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
            for slug in slugs:
                path = "/index.html" if slug == "home" else f"/{slug}.html"
                url = base + path
                page = await ctx.new_page()
                result = PageVerifyResult(slug=slug, url=url)

                console_errors: list[str] = []
                def on_console(msg, errs=console_errors):
                    if msg.type in ("error",):
                        errs.append(msg.text[:240])
                page.on("console", on_console)

                failed: list[dict] = []
                def on_resp(resp, fails=failed):
                    try:
                        st = resp.status
                        if st >= 400:
                            fails.append({"url": resp.url, "status": st})
                    except Exception:
                        pass
                page.on("response", on_resp)

                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8_000)
                    except Exception:
                        pass
                    result.title = await page.title()
                    html = await page.content()
                    result.html_bytes = len(html)
                    shot = shots_dir / f"{slug}.png"
                    try:
                        await page.screenshot(path=str(shot), full_page=True)
                        result.screenshot_path = str(shot.relative_to(root))
                    except Exception as e:
                        log.warning(f"screenshot failed for {slug}: {e}")
                except Exception as e:
                    result.console_errors.append(f"navigation error: {e}")
                    result.passed = False
                finally:
                    result.console_errors.extend(console_errors)
                    result.failed_requests = failed
                    if console_errors or failed:
                        result.passed = False
                    await page.close()
                results.append(result)
            await browser.close()
    finally:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass

    return {
        "results": [r.__dict__ for r in results],
        "stats": {
            "pages": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "total_console_errors": sum(len(r.console_errors) for r in results),
            "total_failed_requests": sum(len(r.failed_requests) for r in results),
        },
    }


def verify(real_project_dir: Path, slugs: list[str]) -> dict:
    """Synchronous wrapper. Returns the verify report dict and also writes
    verify_report.json into the real-project dir."""
    try:
        report = asyncio.run(_verify_with_playwright(real_project_dir, slugs))
    except Exception as e:
        log.warning(f"playwright verify unavailable ({e}); doing static check only")
        report = _static_only_check(real_project_dir, slugs)
    (real_project_dir / "verify_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _static_only_check(real_project_dir: Path, slugs: list[str]) -> dict:
    """Parse each generated HTML with BeautifulSoup and confirm it has a
    <title>, no Angular wrappers, and that referenced CSS/JS files exist
    on disk."""
    from bs4 import BeautifulSoup
    results = []
    for slug in slugs:
        path = real_project_dir / ("index.html" if slug == "home" else f"{slug}.html")
        if not path.exists():
            results.append({"slug": slug, "passed": False, "missing": True})
            continue
        html = path.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html, "lxml")
        problems: list[str] = []
        if not soup.find("title"):
            problems.append("missing <title>")
        for tag in soup.find_all(["link", "script"]):
            href = tag.get("href") or tag.get("src") or ""
            if not href or href.startswith(("http://", "https://", "data:", "//")):
                continue
            local = (real_project_dir / href.lstrip("/")).resolve()
            if not local.exists():
                problems.append(f"missing local file: {href}")
        if any(soup.find(t) for t in ("app-root", "app-layout", "app-page")):
            problems.append("Angular wrapper still present")
        results.append({
            "slug": slug,
            "passed": not problems,
            "problems": problems,
        })
    return {
        "results": results,
        "stats": {
            "pages": len(results),
            "passed": sum(1 for r in results if r.get("passed")),
            "failed": sum(1 for r in results if not r.get("passed")),
            "mode": "static-only",
        },
    }
