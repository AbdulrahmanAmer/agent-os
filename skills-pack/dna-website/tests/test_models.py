"""
Tests for scripts/models.py.

Focus: every model can round-trip through JSON, optional fields work
as expected, and the SCHEMA_VERSION is wired into the right places.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.models import (
    SCHEMA_VERSION,
    AccentColors,
    Asset,
    AssetManifest,
    AssetStats,
    BrandColors,
    Capture,
    CaptureFiles,
    CaptureManifest,
    ColorPalette,
    DesignTokens,
    PageMeta,
    Route,
    RouteList,
    RunManifest,
    TokenValue,
    Viewport,
    load_model,
    write_model,
)


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

def test_schema_version_is_string():
    assert isinstance(SCHEMA_VERSION, str)
    assert SCHEMA_VERSION.count(".") == 1   # major.minor


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------

class TestRoundTrips:
    """Every model should survive JSON encode → decode unchanged."""

    def test_route(self):
        r = Route(
            url="https://example.com/about",
            slug="about",
            depth=1,
            source="crawl",
            discovered_at=datetime(2026, 5, 11, 12, 0, 0),
        )
        loaded = Route.model_validate(json.loads(r.model_dump_json()))
        assert loaded == r

    def test_route_list(self):
        rl = RouteList(
            base_origin="https://example.com",
            routes=[
                Route(url="https://example.com/", slug="home", depth=0, source="seed",
                      discovered_at=datetime.utcnow()),
                Route(url="https://example.com/about", slug="about", depth=1, source="crawl",
                      discovered_at=datetime.utcnow()),
            ],
        )
        loaded = RouteList.model_validate(json.loads(rl.model_dump_json()))
        assert len(loaded.routes) == 2
        assert loaded.routes[0].slug == "home"

    def test_token_value(self):
        tv = TokenValue(value="#1A56DB", frequency=42)
        loaded = TokenValue.model_validate(json.loads(tv.model_dump_json()))
        assert loaded.value == "#1A56DB"
        assert loaded.frequency == 42

    def test_color_palette_minimal(self):
        cp = ColorPalette(
            brand=BrandColors(),
            neutrals={},
            accent=AccentColors(),
        )
        loaded = ColorPalette.model_validate(json.loads(cp.model_dump_json()))
        assert loaded.brand.primary is None

    def test_color_palette_populated(self):
        cp = ColorPalette(
            brand=BrandColors(
                primary=TokenValue(value="#1A56DB", frequency=100),
                secondary=TokenValue(value="#1043B6", frequency=40),
            ),
            neutrals={"50": TokenValue(value="#F9FAFB", frequency=200)},
            accent=AccentColors(success=TokenValue(value="#16A34A", frequency=15)),
        )
        loaded = ColorPalette.model_validate(json.loads(cp.model_dump_json()))
        assert loaded.brand.primary.value == "#1A56DB"
        assert "50" in loaded.neutrals
        assert loaded.accent.success.value == "#16A34A"

    def test_asset(self):
        a = Asset(
            original_url="https://cdn.example.com/img/hero.jpg",
            local_path="raw/assets/images/abc123.jpg",
            content_hash="abc123def456",
            content_type="image/jpeg",
            size_bytes=128_000,
            type="image",
            used_on_pages=["home", "about"],
        )
        loaded = Asset.model_validate(json.loads(a.model_dump_json()))
        assert loaded == a

    def test_capture(self):
        files = CaptureFiles(
            source_html="raw/pages/home/source.html",
            rendered_html="raw/pages/home/rendered.html",
            screenshot_desktop="raw/pages/home/screenshot.desktop.png",
            computed_styles="raw/pages/home/computed-styles.json",
            dom_tree="raw/pages/home/dom-tree.json",
            a11y_tree="raw/pages/home/a11y-tree.json",
            network_log="raw/pages/home/network-log.json",
            meta="raw/pages/home/meta.json",
        )
        c = Capture(
            url="https://example.com/",
            slug="home",
            status="ok",
            duration_ms=1234,
            http_status=200,
            files=files,
            viewport=Viewport(width=1440, height=900),
        )
        loaded = Capture.model_validate(json.loads(c.model_dump_json()))
        assert loaded.status == "ok"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_capture_rejects_invalid_status(self):
        with pytest.raises(ValidationError):
            Capture(
                url="https://x.com/", slug="x", status="weird",   # type: ignore
                duration_ms=0, http_status=200,
                files=CaptureFiles(
                    source_html="x", rendered_html="x",
                    screenshot_desktop="x", computed_styles="x",
                    dom_tree="x", a11y_tree="x", network_log="x", meta="x",
                ),
                viewport=Viewport(width=1, height=1),
            )

    def test_route_requires_url(self):
        with pytest.raises(ValidationError):
            Route(slug="x", depth=0, source="crawl", discovered_at=datetime.utcnow())   # type: ignore

    def test_token_value_frequency_optional(self):
        tv = TokenValue(value="#FFFFFF")
        assert tv.frequency is None


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

class TestWriteLoad:
    def test_write_and_load_route_list(self, tmp_path):
        rl = RouteList(
            base_origin="https://example.com",
            routes=[Route(url="https://example.com/", slug="home", depth=0,
                          source="seed", discovered_at=datetime(2026, 1, 1))],
        )
        path = tmp_path / "routes.json"
        write_model(path, rl)
        assert path.exists()
        loaded = load_model(path, RouteList)
        assert loaded.routes[0].slug == "home"

    def test_load_model_raises_on_schema_mismatch(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"not": "a route list"}))
        with pytest.raises(ValidationError):
            load_model(path, RouteList)
