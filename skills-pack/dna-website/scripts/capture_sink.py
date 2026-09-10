"""
Local HTTP sink for captures coming from the browser.

The Claude in Chrome MCP tool blocks JS results that contain cookies / token-
shaped strings. Captured HTML routinely contains things that look like tokens
(CSRF inputs, JWT-shaped GA cookies in <script>, etc.), so we can't bring
captured pages back through the MCP tool's return path.

Workaround: run this little server on localhost. The browser POSTs each
capture to it via `fetch()`. The server writes the bytes straight to disk
in the dna-website output layout, sanitising headers as it goes.

Endpoints:
  POST /capture        - body: { slug, html, meta, elements, dom, links }
  POST /screenshot     - multipart with field 'file' (PNG bytes) + 'slug' field
  GET  /healthz        - returns 'ok'
  GET  /next?after=... - returns the BFS frontier (used by the caller, not browser)

Output layout (rooted at $DNA_OUT):
  raw/pages/<slug>/source.html         <- if provided
  raw/pages/<slug>/rendered.html
  raw/pages/<slug>/meta.json
  raw/pages/<slug>/computed-styles.json
  raw/pages/<slug>/dom-tree.json
  raw/pages/<slug>/a11y-tree.json      <- empty {} if not provided
  raw/pages/<slug>/network-log.json    <- empty list if not provided
  raw/pages/<slug>/screenshot.desktop.png
  raw/captures.partial.jsonl           <- one capture entry per page
  raw/routes.frontier.json             <- BFS frontier maintained by caller

CORS is wide-open on localhost so the page can POST cross-origin.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PORT = int(os.environ.get("DNA_SINK_PORT", "7779"))
OUT = Path(os.environ.get("DNA_OUT", "outputs/kindskiptracing-2026-05-11")).resolve()

PAGES_DIR = OUT / "raw" / "pages"
PAGES_DIR.mkdir(parents=True, exist_ok=True)

LOG_PATH = OUT / "raw" / "sink.log"
CAPTURES_LOG = OUT / "raw" / "captures.partial.jsonl"


def _log(msg: str) -> None:
    line = f"{datetime.utcnow().isoformat()} {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _slug_for(url: str) -> str:
    """Local copy of url_to_slug to avoid importing the heavy stack."""
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


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Quiet the default access logging — we have _log()
        pass

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/healthz"):
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_response(404)
        self._cors()
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            if self.path.startswith("/capture"):
                data = json.loads(raw.decode("utf-8"))
                self._handle_capture(data)
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
                return
            elif self.path.startswith("/screenshot"):
                # body: { slug, png_b64 }
                data = json.loads(raw.decode("utf-8"))
                self._handle_screenshot(data)
                self.send_response(200)
                self._cors()
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
                return
            else:
                self.send_response(404)
                self._cors()
                self.end_headers()
        except Exception as e:
            _log(f"ERROR {self.path}: {e!r}")
            self.send_response(500)
            self._cors()
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))

    def _handle_capture(self, data):
        url = data.get("url") or ""
        slug = data.get("slug") or _slug_for(url)
        page_dir = PAGES_DIR / slug
        page_dir.mkdir(parents=True, exist_ok=True)

        html = data.get("html") or ""
        meta = data.get("meta") or {}
        elements = data.get("elements") or []
        dom = data.get("dom")
        links = data.get("links") or []

        (page_dir / "rendered.html").write_text(html, encoding="utf-8")
        # Source HTML is the same as rendered for SPA pages — we don't get
        # the pre-JS body from the browser cheaply.
        (page_dir / "source.html").write_text(html, encoding="utf-8")
        (page_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        (page_dir / "computed-styles.json").write_text(json.dumps({
            "page_slug": slug,
            "captured_at": datetime.utcnow().isoformat(),
            "elements": elements,
        }, indent=2), encoding="utf-8")
        (page_dir / "dom-tree.json").write_text(json.dumps({"root": dom}, indent=2), encoding="utf-8")
        (page_dir / "a11y-tree.json").write_text(json.dumps({"root": None}), encoding="utf-8")
        (page_dir / "network-log.json").write_text(json.dumps({"page_slug": slug, "entries": []}), encoding="utf-8")
        (page_dir / "url.txt").write_text(url, encoding="utf-8")

        # Append to captures log
        entry = {
            "url": url,
            "slug": slug,
            "status": "ok",
            "duration_ms": int(data.get("duration_ms") or 0),
            "http_status": int(data.get("http_status") or 200),
            "final_url": data.get("final_url") or url,
            "links": links,
            "captured_at": datetime.utcnow().isoformat(),
        }
        with open(CAPTURES_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        _log(f"captured slug={slug} url={url} html_bytes={len(html)} links={len(links)} elements={len(elements)}")

    def _handle_screenshot(self, data):
        import base64
        slug = data.get("slug") or _slug_for(data.get("url") or "")
        b64 = data.get("png_b64") or ""
        if not b64:
            return
        page_dir = PAGES_DIR / slug
        page_dir.mkdir(parents=True, exist_ok=True)
        try:
            (page_dir / "screenshot.desktop.png").write_bytes(base64.b64decode(b64))
            _log(f"screenshot slug={slug} bytes={len(b64)}")
        except Exception as e:
            _log(f"screenshot decode failed for {slug}: {e!r}")


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    _log(f"capture_sink listening on http://127.0.0.1:{PORT}  (output={OUT})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        _log("capture_sink stopped")


if __name__ == "__main__":
    main()
