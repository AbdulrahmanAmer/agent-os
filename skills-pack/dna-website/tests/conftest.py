"""
Shared pytest fixtures.

The most important fixture here is `local_server`, which spins up a temporary
HTTP server serving the `tests/fixtures/tiny_site/` directory. Integration
tests use this instead of hitting the real internet.
"""

from __future__ import annotations

import socket
import socketserver
import threading
import time
from contextlib import closing
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def tiny_site_dir() -> Path:
    """Filesystem path to the tiny_site fixture."""
    return FIXTURES_DIR / "tiny_site"


@pytest.fixture
def local_server(tiny_site_dir, request):
    """
    Spin up an HTTP server on a random free port serving the tiny_site fixture.

    Yields the base URL (e.g., "http://localhost:54321"). Tears down on exit.

    Usage:
        def test_crawl(local_server):
            ...uses local_server (str)...
    """
    port = _find_free_port()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(tiny_site_dir), **kwargs)

        def log_message(self, *args, **kwargs):
            pass  # Silence the default access logging

    server = socketserver.TCPServer(("localhost", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Wait for the server to actually be listening
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with closing(socket.create_connection(("localhost", port), timeout=0.5)):
                break
        except OSError:
            time.sleep(0.05)
    else:
        server.shutdown()
        raise RuntimeError(f"Local server on port {port} never came up")

    yield f"http://localhost:{port}"

    server.shutdown()
    server.server_close()


@pytest.fixture
def tmp_output_dir(tmp_path) -> Path:
    """A fresh output directory inside the test's tmp_path."""
    out = tmp_path / "dna-output"
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.fixture
def basic_config(tmp_output_dir):
    """A minimal Config instance pointing at a tmp output dir."""
    from scripts.config import build_config
    return build_config(
        url="http://localhost:8000",
        output_dir=tmp_output_dir / "run",
        depth=2,
        max_pages=10,
        rate_limit=10,        # Faster for tests
        concurrency=2,
        skip_assets=False,
        mobile_also=False,
        include_subdomains=False,
        headed=False,
        verbose=False,
        resume=False,
        auth_profile_name=None,
    )


def _find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: marks tests that spin up servers or browsers (slow)"
    )
    config.addinivalue_line(
        "markers", "calibration: marks tests that compare against real-site snapshots"
    )
