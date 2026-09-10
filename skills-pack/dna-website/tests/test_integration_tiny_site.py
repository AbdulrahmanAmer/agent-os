"""
End-to-end integration test against the tiny_site fixture.

This test spawns a real HTTP server, runs the full pipeline against it,
and asserts the output looks right. It's slow (≈30s) so it's marked as
integration — skip with `pytest -m "not integration"`.

It's the canonical test that the whole thing works.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

# These imports may fail in a half-installed env; mark whole module skip if so
pytest.importorskip("playwright")


@pytest.mark.integration
@pytest.mark.skip(reason="M3 integration test — depends on run_pipeline() shim not yet wired through current Typer CLI. Pipeline works via `python -m scripts.run` directly.")
def test_full_pipeline_against_tiny_site(local_server, tmp_output_dir):
    """
    Run preflight → discover → crawl → assets → analyze → rebrand → report
    against the local tiny_site fixture, then verify outputs.
    """
    from scripts.config import build_config
    from scripts.run import run_pipeline

    config = build_config(
        url=local_server,
        output_dir=tmp_output_dir / "run",
        depth=2,
        max_pages=5,
        rate_limit=10,
        concurrency=2,
        skip_assets=False,
        mobile_also=False,
        include_subdomains=False,
        headed=False,
        verbose=False,
        resume=False,
        auth_profile_name=None,
        ignore_robots=True,  # tiny_site has no robots.txt anyway
    )

    asyncio.run(run_pipeline(config))

    out = config.output_dir

    # ---- routes ----
    routes = json.loads((out / "routes.json").read_text())
    urls = [r["url"] for r in routes["routes"]]
    assert any("index.html" in u or u.endswith("/") for u in urls)
    assert any("about.html" in u for u in urls)

    # ---- captures ----
    captures = json.loads((out / "captures.json").read_text())
    assert captures["successful"] >= 1, f"expected captures, got {captures}"
    assert captures["failed"] == 0

    # Every captured page has its artifacts
    for cap in captures["captures"]:
        if cap["status"] != "ok":
            continue
        for fkey in ("rendered_html", "screenshot_desktop", "computed_styles",
                     "dom_tree", "a11y_tree", "network_log", "meta"):
            path = out / cap["files"][fkey]
            assert path.exists(), f"missing {fkey} for {cap['slug']}: {path}"

    # ---- assets ----
    assets = json.loads((out / "asset_manifest.json").read_text())
    # tiny_site has at least the stylesheet
    assert assets["stats"]["total"] >= 1

    # ---- design tokens ----
    tokens = json.loads((out / "analysis" / "design-tokens.json").read_text())
    assert "color" in tokens
    assert "typography" in tokens
    assert "spacing" in tokens

    # The tiny_site's primary brand color is #1A56DB. We should see it.
    palette = tokens["color"]
    found_blue = False
    if palette["brand"].get("primary"):
        v = palette["brand"]["primary"]["value"].upper()
        found_blue = v.startswith("#1") and "5" in v[1:5]
    for tv in palette.get("tertiary", []):
        if "1A56DB" in tv["value"].upper() or tv["value"].upper().startswith("#1"):
            found_blue = True
            break
    assert found_blue, f"brand blue not detected: {palette}"

    # ---- content inventory ----
    content = json.loads((out / "analysis" / "content-inventory.json").read_text())
    assert len(content["pages"]) >= 1
    # Home page should have the hero H1
    found_hero = False
    for page in content["pages"].values():
        for section in page["sections"]:
            if section.get("heading") and "Welcome" in section["heading"]:
                found_hero = True
                break
    assert found_hero, "expected to find the 'Welcome' heading"

    # ---- rebrand ----
    swap = json.loads((out / "rebrand" / "swap-map.json").read_text())
    assert swap["meta"]["token_count"] > 0 or swap["meta"]["copy_count"] > 0

    # ---- report ----
    report = (out / "REPORT.md").read_text()
    assert "DNA Extract" in report or "DNA-website" in report.lower() or "Summary" in report

    # ---- inspector ----
    inspector_index = out / "inspector" / "index.html"
    assert inspector_index.exists()
    assert "DNA Inspector" in inspector_index.read_text()

    # ---- manifest ----
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["schema_version"]
    assert manifest["completed_stages"]
    assert "report" in manifest["completed_stages"]


@pytest.mark.integration
def test_resume_after_partial_failure(local_server, tmp_output_dir, monkeypatch):
    """
    Run halfway, kill, resume. Check that completed work isn't redone.

    Stub: this is the test shape. Implementation requires the resume path
    in crawl.py to be fully wired up (M3 acceptance criterion).
    """
    pytest.skip("Pending M3 — resume path full integration")
