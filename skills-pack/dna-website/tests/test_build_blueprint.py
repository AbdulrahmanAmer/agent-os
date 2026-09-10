"""Tests for scripts/build_blueprint.py — the normalized design blueprint
extractor (Python port of v1's wp-blueprint/design-from-html.js).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_blueprint import (
    DEFAULTS,
    color_stats,
    derive,
    is_interesting,
    normalize_color,
    rank_colors,
    rgb_to_hex,
)


class TestNormalizeColor:
    def test_hex_long(self):
        assert normalize_color("#F96138") == "#f96138"

    def test_hex_short(self):
        assert normalize_color("#abc") == "#aabbcc"

    def test_hex_with_alpha_truncated(self):
        # 8-char hex (#RRGGBBAA) is truncated to #RRGGBB
        assert normalize_color("#F96138FF") == "#f96138"

    def test_rgb(self):
        assert normalize_color("rgb(249, 97, 56)") == "#f96138"

    def test_rgba(self):
        assert normalize_color("rgba(249, 97, 56, 0.5)") == "#f96138"

    def test_invalid(self):
        assert normalize_color("not a color") is None
        assert normalize_color("") is None
        assert normalize_color(None) is None


class TestRgbToHex:
    def test_basic(self):
        assert rgb_to_hex("rgb(255, 0, 0)") == "#ff0000"

    def test_rgba(self):
        assert rgb_to_hex("rgba(0, 255, 0, 0.8)") == "#00ff00"

    def test_garbage(self):
        assert rgb_to_hex("nothing") is None


class TestIsInteresting:
    def test_brand_orange_is_interesting(self):
        assert is_interesting("#f96138")

    def test_pure_black_not(self):
        assert not is_interesting("#000000")

    def test_pure_white_not(self):
        assert not is_interesting("#ffffff")

    def test_neutral_grey_not(self):
        # low saturation
        assert not is_interesting("#808080")

    def test_dark_navy_passes_interesting(self):
        # #0b1222 is the Kind Skiptracing brand secondary. Luminance ~0.09
        # and (max-min)/(max+min) saturation ~0.51 — both above the
        # v1 thresholds (0.04 lum, 0.12 sat). This is why the v1 blueprint
        # successfully classifies it as secondary and our port matches.
        assert is_interesting("#0b1222") is True


class TestColorStats:
    def test_brand_orange(self):
        lum, sat = color_stats("#f96138")
        assert 0.4 < lum < 0.7
        assert sat > 0.5


class TestRankColors:
    def test_button_weight_boost(self):
        # Plain CSS has two greys, one orange; button context has orange.
        css = "#ff0000\n#00ff00\n#ff0000\n#00ff00\n#ff0000"  # red 3x, green 2x
        button_ctx = ["#00ff00"]  # boosts green by +25
        ranked = rank_colors(css, button_ctx)
        # Green should now beat red because of the button boost
        assert ranked[0][0] == "#00ff00"

    def test_neutrals_filtered(self):
        css = "#000000\n#ffffff\n#808080\n#f96138"
        ranked = rank_colors(css, [])
        # Only the brand orange should pass the is_interesting filter
        assert len(ranked) == 1
        assert ranked[0][0] == "#f96138"


FIXTURE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<title>Test</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Urbanist:wght@400;700&family=Inter&display=swap">
<style>
.btn-primary { background: #f96138; color: white; }
.btn-secondary { color: #f96138; }
.hero h1 { color: #0b1222; font-family: Urbanist, sans-serif; }
.cta-banner { background: #f96138; }
</style>
</head>
<body style="background-color: #ffffff; color: #222222">
  <header style="background-color: #ffffff" class="sticky-header">
    <a class="btn btn-primary" href="/buy">Buy</a>
  </header>
  <main>
    <h1>Welcome</h1>
    <button style="background:#f96138; color:#fff">Sign Up</button>
    <a class="btn" style="background:#0095f6; color:#fff">Learn More</a>
  </main>
  <footer style="background-color: #1a1a1a"></footer>
</body>
</html>
"""


class TestDerive:
    def test_no_pages_dir_uses_defaults(self, tmp_path):
        bp = derive(tmp_path)
        assert bp["colors"]["primary"] == DEFAULTS["colors"]["primary"]

    def test_full_derive_from_fixture(self, tmp_path):
        pages = tmp_path / "raw" / "pages" / "home"
        pages.mkdir(parents=True)
        (pages / "rendered.html").write_text(FIXTURE_HTML, encoding="utf-8")
        bp = derive(tmp_path)
        # Brand orange should be primary (boosted via button-context)
        assert bp["colors"]["primary"] == "#f96138"
        # Body bg / footer bg / text peeked from inline styles
        assert bp["colors"]["background"] == "#ffffff"
        assert bp["colors"]["text"] == "#222222"
        assert bp["colors"]["footer_bg"] == "#1a1a1a"
        # Google fonts parsed
        assert "Urbanist" in bp["google_fonts_detected"]
        assert "Inter" in bp["google_fonts_detected"]
        # Heading font picked from google fonts
        assert bp["fonts"]["heading"]["family"] in ("Urbanist", "Inter")
        # Header sticky detected
        assert bp["header"]["style"] == "sticky"
        # Primary button bg matches primary color
        assert bp["buttons"]["primary"]["bg"] == "#f96138"

    def test_cross_validates_with_design_tokens(self, tmp_path):
        """If analyze_dna already wrote design-tokens.json with a different
        clustered primary, build_blueprint should prefer the clustered value
        and surface the heuristic guess in alternates[]."""
        pages = tmp_path / "raw" / "pages" / "home"
        pages.mkdir(parents=True)
        (pages / "rendered.html").write_text(FIXTURE_HTML, encoding="utf-8")
        analysis = tmp_path / "analysis"
        analysis.mkdir()
        # Pretend analyze_dna clustered #f96138 (will agree, no alternate)
        (analysis / "design-tokens.json").write_text(json.dumps({
            "color": {"brand": {"primary": {"value": "#F96138", "frequency": 100}}}
        }), encoding="utf-8")
        bp = derive(tmp_path)
        assert bp["colors"]["primary"] == "#f96138"
        assert bp["colors"]["alternates"] == []

    def test_alternates_when_disagree(self, tmp_path):
        pages = tmp_path / "raw" / "pages" / "home"
        pages.mkdir(parents=True)
        (pages / "rendered.html").write_text(FIXTURE_HTML, encoding="utf-8")
        analysis = tmp_path / "analysis"
        analysis.mkdir()
        # Cluster says different color
        (analysis / "design-tokens.json").write_text(json.dumps({
            "color": {"brand": {"primary": {"value": "#0000ff", "frequency": 100}}}
        }), encoding="utf-8")
        bp = derive(tmp_path)
        # Cluster wins on primary
        assert bp["colors"]["primary"] == "#0000ff"
        # Heuristic guess captured in alternates
        assert "#f96138" in bp["colors"]["alternates"]
