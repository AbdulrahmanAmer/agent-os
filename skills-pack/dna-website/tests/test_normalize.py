"""Tests for the deterministic parts of scripts/normalize/.

The AI-powered modules are exercised in mock mode (DNA_NORMALIZE_MOCK_LLM=1)
so the suite runs without an API key.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

# Force the LLM into mock mode for every test in this file. Set BEFORE
# importing anything that touches LLMClient.
os.environ["DNA_NORMALIZE_MOCK_LLM"] = "1"

from scripts.normalize.llm import LLMClient
from scripts.normalize.strip_spa import (
    NG_ATTR_RE,
    SPA_ELEMENT_RENAMES,
    strip_spa,
)
from scripts.normalize.rewrite_assets import (
    ANALYTICS_HOSTS,
    copy_assets,
    write_asset_index,
)
from scripts.normalize.extract_css import _render_tokens_css, _strip_angular, CssExtractStats
from scripts.normalize import wire_interactions


class TestStripSpa:
    def test_removes_runtime_scripts(self):
        html = """<!doctype html><html><head>
        <script src="/assets/runtime-abc123.js"></script>
        <script src="/assets/polyfills-def456.js"></script>
        <script src="/assets/main.6e9d3.js"></script>
        <script src="https://example.com/normal.js"></script>
        </head><body></body></html>"""
        cleaned, stats = strip_spa(html)
        assert stats.scripts_removed == 3
        assert "runtime-abc123.js" not in cleaned
        assert "polyfills-def456.js" not in cleaned
        assert "normal.js" in cleaned  # non-runtime survives

    def test_removes_modulepreload(self):
        html = """<head>
        <link rel="modulepreload" href="/main.js">
        <link rel="preload" as="script" href="/runtime.js">
        <link rel="stylesheet" href="/style.css">
        </head>"""
        cleaned, stats = strip_spa(html)
        assert stats.preload_links_removed == 2
        assert "style.css" in cleaned

    def test_removes_base_href(self):
        html = '<head><base href="/"><title>X</title></head>'
        cleaned, stats = strip_spa(html)
        assert stats.base_removed == 1
        assert "<base" not in cleaned

    def test_strips_ng_attrs(self):
        html = '<div _nghost-abc="" _ngcontent-def="" ng-version="17.0.0" class="x">hi</div>'
        cleaned, stats = strip_spa(html)
        assert stats.ng_attrs_removed >= 3
        assert "_nghost" not in cleaned
        assert "_ngcontent" not in cleaned
        assert "ng-version" not in cleaned
        assert 'class="x"' in cleaned

    def test_renames_known_spa_elements(self):
        html = "<app-root><app-layout><app-header></app-header><app-footer></app-footer></app-layout></app-root>"
        cleaned, stats = strip_spa(html)
        # app-root + app-layout → div; app-header → header; app-footer → footer
        assert stats.spa_elements_renamed.get("app-root") == 1
        assert stats.spa_elements_renamed.get("app-header") == 1
        assert "<header" in cleaned
        assert "<footer" in cleaned
        assert "<app-root" not in cleaned

    def test_unknown_app_element_downgrades_to_div(self):
        html = "<app-custom-widget>hi</app-custom-widget>"
        cleaned, stats = strip_spa(html)
        assert stats.spa_elements_renamed.get("app-custom-widget") == 1
        assert "<div" in cleaned and "<app-custom-widget" not in cleaned

    def test_removes_enable_js_noscript(self):
        html = "<body><noscript>Please enable JavaScript to view this.</noscript><p>hi</p></body>"
        cleaned, stats = strip_spa(html)
        assert stats.noscript_removed == 1
        assert "<p>hi</p>" in cleaned

    def test_preserves_visible_text(self):
        html = """<html><head><script src="/runtime.js"></script></head><body>
        <app-root><h1>Hello world</h1><p>A real paragraph.</p></app-root></body></html>"""
        cleaned, _ = strip_spa(html)
        assert "Hello world" in cleaned
        assert "A real paragraph." in cleaned


class TestRewriteAssets:
    def test_copy_local_and_skip_analytics(self, tmp_path):
        capture = tmp_path / "capture"
        target = tmp_path / "real"
        # Create a fake asset to copy
        (capture / "assets" / "images").mkdir(parents=True)
        (capture / "assets" / "images" / "abc.webp").write_bytes(b"PNG")
        # Stylesheet too
        (capture / "assets" / "stylesheets").mkdir(parents=True)
        (capture / "assets" / "stylesheets" / "site.css").write_text("body{}", encoding="utf-8")

        manifest = {
            "assets": [
                # Same-host image — should copy
                {
                    "original_url": "https://kindskiptracing.com/img/abc.webp",
                    "local_path": "assets/images/abc.webp",
                    "content_hash": "ffff", "content_type": "image/webp",
                    "size_bytes": 3, "type": "image",
                },
                # Analytics — should strip (no copy, no map entry)
                {
                    "original_url": "https://www.google-analytics.com/g/collect",
                    "local_path": "assets/scripts/ga.js",
                    "content_hash": "g1", "content_type": "application/javascript",
                    "size_bytes": 0, "type": "script",
                },
                # Cross-origin font — should keep URL as-is, no copy
                {
                    "original_url": "https://fonts.gstatic.com/s/urbanist/v17/font.woff2",
                    "local_path": "",
                    "content_hash": "ff", "content_type": "font/woff2",
                    "size_bytes": 0, "type": "font",
                },
                # Same-host CSS — should copy
                {
                    "original_url": "https://kindskiptracing.com/styles.css",
                    "local_path": "assets/stylesheets/site.css",
                    "content_hash": "css1", "content_type": "text/css",
                    "size_bytes": 5, "type": "stylesheet",
                },
            ]
        }
        result = copy_assets(capture, target, manifest, source_host="https://kindskiptracing.com")
        # Image + css copied
        assert result.assets_copied == 2
        assert (target / "assets/images/abc.webp").exists()
        assert (target / "assets/stylesheets/site.css").exists()
        # Analytics stripped
        assert any("google-analytics" in u for u in result.analytics_stripped)
        # Cross-origin kept as-is
        assert "https://fonts.gstatic.com/s/urbanist/v17/font.woff2" in result.cross_origin_kept
        # Image URL mapped to local relative path
        assert result.url_to_local["https://kindskiptracing.com/img/abc.webp"] == "assets/images/abc.webp"
        # Cross-origin URL maps to itself
        assert result.url_to_local["https://fonts.gstatic.com/s/urbanist/v17/font.woff2"] == "https://fonts.gstatic.com/s/urbanist/v17/font.woff2"
        # Analytics has no map entry
        assert "https://www.google-analytics.com/g/collect" not in result.url_to_local

    def test_write_asset_index_writes_json(self, tmp_path):
        from scripts.normalize.rewrite_assets import RewriteResult
        result = RewriteResult(
            url_to_local={"https://x.com/a.png": "assets/images/a.png"},
            assets_copied=1, bytes_copied=100,
            cross_origin_kept=["https://fonts.googleapis.com/css?family=Urbanist"],
            analytics_stripped=["https://www.google-analytics.com/g/collect"],
        )
        write_asset_index(tmp_path, result)
        data = json.loads((tmp_path / "assets.json").read_text())
        assert data["stats"]["copied"] == 1
        assert data["stats"]["cross_origin_kept"] == 1


class TestExtractCss:
    def test_render_tokens_css_includes_brand(self):
        tokens = {
            "color": {
                "brand": {"primary": {"value": "#f96138", "frequency": 100}},
                "neutrals": {"50": {"value": "#f8f8f8"}},
                "accent": {"info": {"value": "#0095f6"}},
            },
            "typography": {
                "families": {
                    "body": {"stack": "Urbanist, sans-serif", "primary": "Urbanist"},
                    "heading": {"stack": "Urbanist, sans-serif", "primary": "Urbanist"},
                },
                "scale": {"sizes": {"base": {"px": 16, "rem": 1.0}, "lg": {"px": 20, "rem": 1.25}}},
            },
            "spacing": {"scale": {"4": {"px": 16, "rem": 1.0}}},
            "radius": {"scale": {"base": 4, "full": 9999}},
            "shadow": {"scale": {"sm": "0 1px 2px rgba(0,0,0,0.1)"}},
            "motion": {"duration": {"base": "200ms"}, "easing": {"out": "ease"}},
            "breakpoint": {"scale": {"md": "768px"}},
        }
        css = _render_tokens_css(tokens)
        assert "--color-brand-primary: #f96138;" in css
        assert "--color-neutral-50: #f8f8f8;" in css
        assert "--color-accent-info: #0095f6;" in css
        assert "--font-body: Urbanist, sans-serif;" in css
        assert "--font-size-base: 1.0rem;" in css
        assert "--space-4: 1.0rem;" in css
        assert "--radius-base: 4px;" in css
        assert "--radius-full: 9999px;" in css
        assert "--shadow-sm: 0 1px 2px rgba(0,0,0,0.1);" in css
        assert "--duration-base: 200ms;" in css
        assert "--breakpoint-md: 768px;" in css

    def test_strip_angular_removes_view_encapsulation(self):
        css = """
.button[_ngcontent-abc-c1] { color: red; }
.standard { color: blue; }
app-button { display: inline-block; }
"""
        stats = CssExtractStats()
        cleaned = _strip_angular(css, stats)
        assert "_ngcontent" not in cleaned
        assert ".standard { color: blue; }" in cleaned
        # The full app-button rule should have been dropped
        assert "app-button { display:" not in cleaned and "app-button{display:" not in cleaned
        assert stats.rules_dropped_angular >= 1


class TestWireInteractionsFallback:
    def test_fallback_runtime_has_no_forbidden_patterns(self):
        fallback = wire_interactions._fallback_runtime()
        js = fallback["js"]
        for pat in wire_interactions.FORBIDDEN_JS_PATTERNS:
            assert not pat.search(js), f"fallback violates {pat.pattern}"
        # Sanity — fallback covers the documented patterns
        for pattern in ("menu-toggle", "modal-triggers", "form-prevent-submit",
                        "purchase-button-warn", "smooth-scroll-anchors"):
            assert pattern in fallback["patterns_wired"]

    def test_static_check_flags_form_submit(self):
        bad_js = "document.querySelector('form').submit();"
        findings = wire_interactions._static_check_js(bad_js)
        assert findings, "static check should flag .submit()"

    def test_static_check_flags_purchase_fetch(self):
        bad_js = "fetch('/buy', {method:'POST'});"
        findings = wire_interactions._static_check_js(bad_js)
        assert findings, "static check should flag fetch to /buy"

    def test_static_check_passes_clean_js(self):
        good_js = "document.addEventListener('click', e => e.preventDefault());"
        assert not wire_interactions._static_check_js(good_js)


class TestClaudeCLIBackend:
    """Direct unit tests on ClaudeCLIBackend via subprocess mocking."""

    def test_envelope_parsed_to_result(self, monkeypatch, tmp_path):
        from scripts.normalize import claude_cli as cc

        called = {}

        class FakeResult:
            returncode = 0
            stderr = ""
            stdout = json.dumps({
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": '{"html": "<p>ok</p>"}',
                "usage": {"input_tokens": 7, "output_tokens": 11,
                          "cache_creation_input_tokens": 100,
                          "cache_read_input_tokens": 200},
                "total_cost_usd": 0.0123,
            })

        def fake_run(cmd, **kwargs):
            called["cmd"] = cmd
            called["stdin"] = kwargs.get("input")
            return FakeResult()

        monkeypatch.setattr(cc.subprocess, "run", fake_run)
        # Force the binary so _resolve_claude_binary doesn't matter
        b = cc.ClaudeCLIBackend("shared system text", binary="C:/fake/claude.exe")
        out = b.ask("hello", expect_json=True)
        assert out == {"html": "<p>ok</p>"}
        # Confirm subprocess was called with the expected flags
        cmd = called["cmd"]
        assert "--print" in cmd
        assert "--output-format" in cmd and "json" in cmd
        assert "--no-session-persistence" in cmd
        assert "--system-prompt-file" in cmd
        assert called["stdin"] == "hello"
        # Usage rolled up
        assert b.usage.calls == 1
        assert b.usage.cache_read_tokens == 200
        assert round(b.usage.total_cost_usd, 4) == 0.0123
        b.close()

    def test_is_error_envelope_raises(self, monkeypatch):
        from scripts.normalize import claude_cli as cc

        class FakeResult:
            returncode = 0
            stderr = ""
            stdout = json.dumps({
                "type": "result", "subtype": "error", "is_error": True,
                "result": "Not logged in · Please run /login",
            })

        monkeypatch.setattr(cc.subprocess, "run", lambda *a, **kw: FakeResult())
        b = cc.ClaudeCLIBackend("sys", binary="C:/fake/claude.exe")
        # 'not logged in' is in the special-cased no-retry list — single attempt
        with pytest.raises(Exception):
            b.ask("hello", max_retries=1)
        b.close()

    def test_strips_json_fence(self):
        from scripts.normalize.claude_cli import _parse_json
        assert _parse_json("```json\n{\"a\": 1}\n```") == {"a": 1}
        assert _parse_json("Here is JSON: {\"x\": [1, 2]} done") == {"x": [1, 2]}


class TestLLMClientBackendSelection:
    def test_explicit_mock_via_env(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("DNA_NORMALIZE_MOCK_LLM", "1")
        c = LLMClient()
        assert c.backend == "mock"
        assert c.mock is True

    def test_explicit_backend_override_to_mock(self, monkeypatch):
        monkeypatch.delenv("DNA_NORMALIZE_MOCK_LLM", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
        monkeypatch.setenv("DNA_NORMALIZE_LLM_BACKEND", "mock")
        c = LLMClient()
        assert c.backend == "mock"

    def test_init_no_api_key_no_cli_falls_to_mock(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("DNA_NORMALIZE_MOCK_LLM", raising=False)
        monkeypatch.delenv("DNA_NORMALIZE_LLM_BACKEND", raising=False)
        # Pretend the CLI isn't on PATH
        from scripts.normalize import claude_cli
        monkeypatch.setattr(claude_cli, "is_claude_cli_available", lambda: False)
        c = LLMClient()
        assert c.backend == "mock"


class TestLLMClientMockMode:
    def test_init_no_api_key_falls_to_mock(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("DNA_NORMALIZE_MOCK_LLM", "1")
        c = LLMClient()
        assert c.mock is True

    def test_mock_returns_dict_for_known_prompts(self):
        c = LLMClient()
        # Force mock mode regardless
        c.mock = True
        reply = c.ask("Please rewrite the page into clean HTML", expect_json=True)
        assert isinstance(reply, dict)
        assert "html" in reply

    def test_parse_json_strips_fences(self):
        c = LLMClient()
        out = c._parse_json('```json\n{"a": 1}\n```')
        assert out == {"a": 1}

    def test_parse_json_finds_embedded_object(self):
        c = LLMClient()
        out = c._parse_json("Here's the JSON:\n{\"x\": [1,2,3]}\nThanks!")
        assert out == {"x": [1, 2, 3]}


class TestEndToEndDeterministic:
    """A tiny end-to-end run in mock mode against a synthetic capture
    fixture. Exercises every stage glue without any AI."""

    def test_smoke_run_writes_expected_files(self, tmp_path):
        # Build a minimal capture dir
        capture = tmp_path / "capture"
        (capture / "raw" / "pages" / "home").mkdir(parents=True)
        (capture / "raw" / "pages" / "home" / "rendered.html").write_text(
            "<!doctype html><html><head><title>Home</title></head>"
            "<body><app-root><h1>Hi</h1></app-root></body></html>",
            encoding="utf-8",
        )
        (capture / "raw" / "pages" / "home" / "meta.json").write_text(
            json.dumps({"title": "Home", "url": "https://example.com/"}), encoding="utf-8")
        (capture / "raw" / "pages" / "home" / "url.txt").write_text("https://example.com/", encoding="utf-8")
        (capture / "raw" / "assets" / "stylesheets").mkdir(parents=True)
        (capture / "_inbox").mkdir()
        (capture / "_inbox" / "home.json").write_text(json.dumps({
            "url": "https://example.com/", "slug": "home",
            "meta": {"title": "Home"},
            "sections": [{"heading": "Hi", "level": 1, "paragraphs": ["Welcome."], "links": [], "images": [], "ctas": []}],
            "compact_styles": {"sampled": 1, "colors": {}, "font_families": {}},
        }), encoding="utf-8")
        (capture / "captures.json").write_text(json.dumps({
            "total": 1, "successful": 1, "failed": 0,
            "captures": [{
                "url": "https://example.com/", "slug": "home", "status": "ok",
                "duration_ms": 0, "http_status": 200,
                "files": {
                    "source_html": "raw/pages/home/source.html",
                    "rendered_html": "raw/pages/home/rendered.html",
                    "screenshot_desktop": "raw/pages/home/screenshot.desktop.png",
                    "computed_styles": "raw/pages/home/computed-styles.json",
                    "dom_tree": "raw/pages/home/dom-tree.json",
                    "a11y_tree": "raw/pages/home/a11y-tree.json",
                    "network_log": "raw/pages/home/network-log.json",
                    "meta": "raw/pages/home/meta.json",
                },
                "viewport": {"width": 1440, "height": 900},
            }],
        }), encoding="utf-8")
        (capture / "asset_manifest.json").write_text(json.dumps({
            "assets": [], "by_url": {}, "stats": {"total": 0, "by_type": {}, "total_bytes": 0, "failed": 0, "skipped_oversized": 0},
        }), encoding="utf-8")
        (capture / "preflight.json").write_text(json.dumps({
            "url": "https://example.com/", "normalized_url": "https://example.com/",
            "domain": "example.com", "base_origin": "https://example.com",
            "blocked_category": None, "robots_allowed": True, "robots_disallow_paths": [],
            "user_confirmed_override": False, "flags": {"ignore_robots": False, "i_own_this_site": False, "include_subdomains": False},
        }), encoding="utf-8")
        (capture / "analysis").mkdir()
        (capture / "analysis" / "design-tokens.json").write_text(json.dumps({
            "color": {"brand": {"primary": {"value": "#f96138", "frequency": 100}}, "neutrals": {}, "accent": {}},
            "typography": {"families": {}, "scale": {"sizes": {}}},
            "spacing": {"scale": {}}, "radius": {"scale": {}},
            "shadow": {"scale": {}}, "motion": {"duration": {}, "easing": {}},
            "breakpoint": {"scale": {}},
        }), encoding="utf-8")
        (capture / "analysis" / "content-inventory.json").write_text(json.dumps({"pages": {}}), encoding="utf-8")
        (capture / "analysis" / "interactive-map.json").write_text(json.dumps({
            "metadata": {"source_url": "https://example.com", "agent": "test", "route_count": 1},
            "routes": [], "aggregate": {"total_links": 0, "total_buttons": 0,
                                        "total_forms": 0, "total_iframes": 0,
                                        "total_accordions": 0, "total_tabs": 0,
                                        "external_destinations": [], "analytics_destinations": [],
                                        "same_origin_form_actions": [], "cross_origin_form_actions": [],
                                        "iframe_purposes": {}},
        }), encoding="utf-8")
        (capture / "analysis" / "design-blueprint.json").write_text(json.dumps({
            "colors": {"primary": "#f96138"}, "fonts": {}, "buttons": {}, "header": {}, "layout": {},
        }), encoding="utf-8")

        target = tmp_path / "real"

        from scripts.normalize.orchestrator import run as orch_run
        report = orch_run(capture, target, skip_verify=True)

        # Expected files
        assert (target / "index.html").exists()
        assert (target / "assets" / "css" / "tokens.css").exists()
        assert (target / "assets" / "css" / "reset.css").exists()
        assert (target / "assets" / "css" / "base.css").exists()
        assert (target / "assets" / "js" / "runtime.js").exists()
        assert (target / "README.md").exists()
        assert (target / "normalize_report.json").exists()
        # tokens.css should have the brand var
        tokens = (target / "assets" / "css" / "tokens.css").read_text(encoding="utf-8")
        assert "--color-brand-primary: #f96138" in tokens
        # runtime.js should not contain forbidden patterns
        rt = (target / "assets" / "js" / "runtime.js").read_text(encoding="utf-8")
        for pat in wire_interactions.FORBIDDEN_JS_PATTERNS:
            assert not pat.search(rt), f"runtime contains forbidden pattern {pat.pattern}"
        # Report should record we ran in mock mode
        assert report["llm"]["mock"] is True
