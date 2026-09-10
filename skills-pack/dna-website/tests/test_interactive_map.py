"""Tests for scripts/interactive_map.py — the v1 port that walks captured
HTML and emits an interactive-element inventory per route.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.interactive_map import (
    ANALYTICS_HOSTS,
    classify_href,
    extract_interactive,
    build,
)


ORIGIN = "https://example.com"


class TestClassifyHref:
    def test_empty(self):
        assert classify_href("", ORIGIN)["kind"] == "empty"

    def test_phone(self):
        out = classify_href("tel:+1-555-0100", ORIGIN)
        assert out == {"kind": "phone", "value": "+1-555-0100"}

    def test_email(self):
        out = classify_href("mailto:hi@example.com", ORIGIN)
        assert out == {"kind": "email", "value": "hi@example.com"}

    def test_javascript(self):
        assert classify_href("javascript:void(0)", ORIGIN)["kind"] == "javascript"

    def test_anchor(self):
        out = classify_href("#section", ORIGIN)
        assert out == {"kind": "anchor", "value": "#section"}

    def test_relative_internal(self):
        out = classify_href("/dashboard", ORIGIN)
        assert out == {"kind": "internal", "path": "/dashboard"}

    def test_absolute_same_origin(self):
        out = classify_href("https://example.com/dashboard?a=1", ORIGIN)
        assert out["kind"] == "internal"
        assert "/dashboard" in out["path"]

    def test_external(self):
        out = classify_href("https://other.example.org/page", ORIGIN)
        assert out["kind"] == "external"
        assert out["host"] == "other.example.org"

    def test_analytics(self):
        out = classify_href("https://www.google-analytics.com/g/collect", ORIGIN)
        assert out["kind"] == "analytics"

    def test_unknown(self):
        # urlparse won't raise; this returns kind=external for unparseable garbage
        out = classify_href("not a real url at all", ORIGIN)
        assert out["kind"] in ("unknown", "external", "internal")


class TestExtractInteractive:
    HTML = """
    <html><body>
      <a href="/dashboard">Dashboard</a>
      <a href="https://other.com" class="btn">External Btn</a>
      <a href="tel:+15550100">Call us</a>
      <a href="mailto:hi@example.com">Email</a>
      <a href="#hero">Skip to hero</a>
      <button type="button" aria-expanded="false" aria-controls="panel-1">Toggle</button>
      <button type="submit">Send</button>
      <button class="cookie-banner-accept">Accept All</button>
      <form action="/contact" method="POST">
        <input name="email" type="email" required>
        <input name="message" type="text" placeholder="Your message">
        <input name="csrf" type="hidden" value="abc">
      </form>
      <iframe src="https://www.google.com/maps/embed?p=1"></iframe>
      <iframe src="https://www.youtube.com/embed/dQw4"></iframe>
      <iframe src="https://js.stripe.com/v3/elements-inner.html"></iframe>
      <details><summary>FAQ Q1</summary><p>A1</p></details>
      <div role="tablist">
        <button role="tab" aria-controls="t1" aria-selected="true">Tab 1</button>
        <button role="tab" aria-controls="t2">Tab 2</button>
      </div>
    </body></html>
    """

    def test_links_present(self):
        ix = extract_interactive(self.HTML, ORIGIN)
        assert len(ix["links"]) == 5
        texts = {l["text"] for l in ix["links"]}
        assert "Dashboard" in texts
        # External link with .btn class flagged as button-link
        external = next(l for l in ix["links"] if l["destination"]["kind"] == "external")
        assert external["role"] == "button-link"

    def test_buttons_classified(self):
        ix = extract_interactive(self.HTML, ORIGIN)
        # 3 buttons (Toggle/Send/Accept All)
        assert len(ix["buttons"]) == 3
        behaviors = {b["inferredBehavior"] for b in ix["buttons"]}
        assert any("toggle-expanded" in b for b in behaviors)
        assert "submit-form" in behaviors
        assert "cookie-banner-accept" in behaviors

    def test_forms_extract_fields_skip_csrf(self):
        ix = extract_interactive(self.HTML, ORIGIN)
        assert len(ix["forms"]) == 1
        form = ix["forms"][0]
        assert form["action"] == "/contact"
        assert form["method"] == "POST"
        # Hidden csrf must be excluded; email + message kept
        field_names = {f["name"] for f in form["fields"]}
        assert "email" in field_names
        assert "message" in field_names
        assert "csrf" not in field_names

    def test_iframe_purpose_inference(self):
        ix = extract_interactive(self.HTML, ORIGIN)
        purposes = {i["purpose"] for i in ix["iframes"]}
        assert "google-map" in purposes
        assert "video-embed" in purposes
        assert "payment-iframe" in purposes

    def test_accordions(self):
        ix = extract_interactive(self.HTML, ORIGIN)
        # 1 details element
        assert any(a["type"] == "details" for a in ix["accordions"])

    def test_tabs(self):
        ix = extract_interactive(self.HTML, ORIGIN)
        labels = {t["label"] for t in ix["tabs"]}
        assert "Tab 1" in labels and "Tab 2" in labels


class TestBuild:
    def test_no_pages_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            build(tmp_path, source_url="https://example.com")

    def test_full_build(self, tmp_path):
        pages = tmp_path / "raw" / "pages" / "home"
        pages.mkdir(parents=True)
        (pages / "rendered.html").write_text(TestExtractInteractive.HTML, encoding="utf-8")
        (pages / "url.txt").write_text("https://example.com/", encoding="utf-8")
        (pages / "meta.json").write_text(json.dumps({"title": "Home"}))
        out = build(tmp_path, source_url="https://example.com")
        assert out["metadata"]["route_count"] == 1
        assert out["routes"][0]["title"] == "Home"
        agg = out["aggregate"]
        assert agg["total_links"] == 5
        assert agg["total_buttons"] == 3
        assert agg["total_forms"] == 1
        assert agg["total_iframes"] == 3
        # 'other.com' should be in external destinations
        assert "other.com" in agg["external_destinations"]
