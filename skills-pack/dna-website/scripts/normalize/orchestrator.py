"""
Normalizer orchestrator.

Drives the full pipeline:

  1. Load capture inputs (design tokens, design blueprint, content
     inventory, interactive map, asset manifest, per-page inbox JSON)
  2. Initialise the LLM client with shared (cacheable) context
  3. Copy static templates (reset.css, package.json)
  4. Run extract_css → tokens.css + raw.css
  5. Run rewrite_assets → copy bytes + url_to_local map
  6. Run consolidate_css (AI) → base.css + components.css
  7. For each page: run generate_html (AI)
  8. Run wire_interactions (AI) → runtime.js + runtime.css
  9. Render README.md from template
 10. Run verify (headless browser smoke + diff)
 11. Write normalize_report.json
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .llm import LLMClient
from .prompts import shared_context_blocks
from . import consolidate_css, extract_css, generate_html, preserve
from . import rewrite_assets, verify, wire_interactions

log = logging.getLogger(__name__)


TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_inbox_payload(capture_dir: Path, slug: str) -> dict:
    p = capture_dir / "_inbox" / f"{slug}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _content_inventory_summary(inv: dict) -> dict:
    """Slim the content-inventory.json down to per-page counts so the
    shared context stays under ~5k tokens."""
    pages = inv.get("pages") or {}
    out = {}
    for slug, page in pages.items():
        out[slug] = {
            "title": page.get("title"),
            "description": (page.get("description") or "")[:200],
            "section_count": len(page.get("sections") or []),
        }
    return out


def run(capture_dir: Path, output_dir: Path, *,
        only_slugs: list[str] | None = None,
        skip_verify: bool = False,
        mode: str = "preserve",
        ai_pages: bool = True,
        ai_css: bool = False,
        ai_runtime: bool = False) -> dict:
    """Run the full normalizer. Returns a summary dict and writes
    normalize_report.json into output_dir.

    Mode:
      "preserve" (default) — keep the captured rendered HTML verbatim;
                strip only the SPA runtime scripts + rewrite asset URLs
                + intercept forms + tag purchase buttons. Produces a
                visually-identical replica that opens directly in VS Code.
                Fast and deterministic; no AI calls.
      "rewrite" — pass each page through the AI cleaner that rewrites it
                into clean semantic HTML5 using design tokens. Higher
                code quality, lower visual fidelity. Slower (one LLM call
                per page).

    Stage toggles (only relevant in "rewrite" mode):
      ai_pages=True   : LLM rewrites each page (default ON).
      ai_css=False    : LLM consolidates base.css (default OFF — fallback
                        ships a production stylesheet).
      ai_runtime=False : LLM builds runtime.js (default OFF — 7-pattern
                         deterministic runtime ships).
    """
    t_start = time.time()
    output_dir = output_dir.resolve()
    capture_dir = capture_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    # 1. Load capture inputs
    design_tokens = _load_json(capture_dir / "analysis" / "design-tokens.json", {})
    design_blueprint = _load_json(capture_dir / "analysis" / "design-blueprint.json", {})
    interactive_map = _load_json(capture_dir / "analysis" / "interactive-map.json", {})
    asset_manifest = _load_json(capture_dir / "asset_manifest.json", {})
    captures = _load_json(capture_dir / "captures.json", {})
    content_inventory = _load_json(capture_dir / "analysis" / "content-inventory.json", {})
    preflight = _load_json(capture_dir / "preflight.json", {})
    base_origin = preflight.get("base_origin") or (captures.get("captures") or [{}])[0].get("url", "")
    domain = preflight.get("domain") or "site"

    # Slug list — keep deterministic order
    all_pages = [c for c in (captures.get("captures") or []) if c.get("status") == "ok"]
    if only_slugs:
        all_pages = [c for c in all_pages if c.get("slug") in only_slugs]

    # 2. LLM client with shared cached context
    shared = shared_context_blocks(
        design_tokens=design_tokens,
        design_blueprint=design_blueprint,
        interactive_map_aggregate=interactive_map.get("aggregate"),
        content_inventory_summary=_content_inventory_summary(content_inventory),
    )
    llm = LLMClient(shared_context=shared)
    log.info(f"LLM backend: {llm.backend} model={llm.model}")

    # 3. Copy templates that don't need rewrites
    css_dir = output_dir / "assets" / "css"
    css_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATES_DIR / "reset.css", css_dir / "reset.css")
    (output_dir / "package.json").write_text(
        (TEMPLATES_DIR / "package.json").read_text(encoding="utf-8")
        .replace("PROJECT_NAME_PLACEHOLDER", domain.replace(".", "-") + "-normalized"),
        encoding="utf-8",
    )

    # 4. CSS extract (tokens + raw)
    css_stats = extract_css.run(capture_dir, output_dir, design_tokens)

    # 5. Asset copy + URL map
    asset_result = rewrite_assets.copy_assets(
        capture_dir, output_dir, asset_manifest, source_host=base_origin,
    )
    # 5b. Rewrite url() refs inside copied CSS files (fonts, bg-image, etc.)
    css_url_rewrites = rewrite_assets.rewrite_urls_inside_css(
        output_dir, asset_result, base_origin,
    )
    if css_url_rewrites:
        log.info(f"  rewrote {css_url_rewrites} url() refs inside captured CSS")
    rewrite_assets.write_asset_index(output_dir, asset_result)

    # 6. CSS consolidate — preserve mode skips this entirely (the original
    # linked CSS does all the visual work). Rewrite mode runs the AI cleaner
    # or our deterministic fallback.
    from .consolidate_css import ConsolidateStats
    if mode == "preserve":
        css_consolidate_stats = ConsolidateStats(
            base_bytes=0, components_bytes=0,
            notes=["skipped — preserve mode uses captured CSS"],
        )
    elif ai_css and llm.backend != "mock":
        css_consolidate_stats = consolidate_css.run(output_dir, design_tokens, llm)
    else:
        from .consolidate_css import FALLBACK_BASE_CSS, FALLBACK_COMPONENTS_CSS
        (css_dir / "base.css").write_text(FALLBACK_BASE_CSS, encoding="utf-8")
        (css_dir / "components.css").write_text(FALLBACK_COMPONENTS_CSS, encoding="utf-8")
        css_consolidate_stats = ConsolidateStats(
            base_bytes=len(FALLBACK_BASE_CSS),
            components_bytes=len(FALLBACK_COMPONENTS_CSS),
            notes=["deterministic fallback (ai_css=False)"],
        )

    # 7. Per-page generate
    page_results = []
    home_slug_candidates = ("home", "index")
    interactive_routes = {r.get("slug"): r for r in (interactive_map.get("routes") or [])}

    # Build slug-by-URL map for internal link rewriting. Three entry kinds:
    #   1. The actually-captured URL (e.g. /order-list/market)
    #   2. The slug-derived path (e.g. /order-list — useful when a captured
    #      page was the SPA-redirected version of a shorter route)
    #   3. The trailing-slash variant of each
    slug_by_url: dict[str, str] = {}
    for cap in all_pages:
        slug = cap.get("slug") or ""
        u = (cap.get("url") or "").rstrip("/")
        if u and slug:
            slug_by_url[u] = slug
            slug_by_url[u + "/"] = slug
        if slug and slug not in ("home", "index"):
            derived = base_origin.rstrip("/") + "/" + slug.replace("__", "/")
            slug_by_url.setdefault(derived, slug)
            slug_by_url.setdefault(derived + "/", slug)
        elif slug in ("home", "index"):
            slug_by_url.setdefault(base_origin.rstrip("/") + "/", slug)
            slug_by_url.setdefault(base_origin.rstrip("/"), slug)

    if mode == "preserve":
        # Preserve mode: keep original DOM/CSS, strip SPA runtime, rewrite URLs.
        # No LLM call per page — deterministic and visually identical.
        for cap in all_pages:
            slug = cap.get("slug") or ""
            url = cap.get("url") or ""
            rendered_path = capture_dir / "raw" / "pages" / slug / "rendered.html"
            if not rendered_path.exists():
                log.warning(f"no rendered HTML for {slug}; skipping")
                continue
            rendered = rendered_path.read_text(encoding="utf-8", errors="ignore")
            is_home = slug in home_slug_candidates
            log.info(f"  preserving page {slug}")
            try:
                out_path, p_stats = preserve.preserve_page(
                    slug=slug,
                    page_url=url,
                    rendered_html=rendered,
                    url_to_local=asset_result.url_to_local,
                    slug_by_url=slug_by_url,
                    base_origin=base_origin,
                    is_home=is_home,
                    home_slug="home",
                    real_project_dir=output_dir,
                )
                result = {
                    "slug": slug,
                    "url": url,
                    "html_path": str(out_path.relative_to(output_dir)).replace("\\", "/"),
                    "html_bytes": p_stats.bytes_out,
                    "notes": ["preserve mode — original DOM/CSS kept verbatim"],
                    "todos": [],
                    "preserve_stats": {
                        "runtime_scripts_removed": p_stats.runtime_scripts_removed,
                        "preload_links_removed": p_stats.preload_links_removed,
                        "inline_scripts_neutralised": p_stats.inline_scripts_neutralised,
                        "asset_urls_rewritten": p_stats.asset_urls_rewritten,
                        "internal_links_rewritten": p_stats.internal_links_rewritten,
                        "forms_dataified": p_stats.forms_dataified,
                        "purchase_buttons_tagged": p_stats.purchase_buttons_tagged,
                    },
                }
            except Exception as e:
                log.error(f"preserve failed for {slug}: {e}")
                result = {"slug": slug, "error": str(e)}
            page_results.append(result)
    else:
        # Rewrite mode (legacy AI/clean path).
        page_llm = llm
        if not ai_pages:
            from .llm import LLMClient as _LC
            import os as _os
            _os.environ["DNA_NORMALIZE_MOCK_LLM"] = "1"
            try:
                page_llm = _LC(shared_context=shared)
            finally:
                _os.environ.pop("DNA_NORMALIZE_MOCK_LLM", None)

        for cap in all_pages:
            slug = cap.get("slug") or ""
            url = cap.get("url") or ""
            rendered_path = capture_dir / "raw" / "pages" / slug / "rendered.html"
            if not rendered_path.exists():
                log.warning(f"no rendered HTML for {slug}; skipping")
                continue
            rendered = rendered_path.read_text(encoding="utf-8", errors="ignore")
            inbox = _load_inbox_payload(capture_dir, slug)
            ix_entry = interactive_routes.get(slug)
            is_home = slug in home_slug_candidates
            log.info(f"  generating page {slug} ({'AI' if ai_pages else 'fallback'})")
            try:
                result = generate_html.generate_page(
                    slug=slug,
                    page_url=url,
                    rendered_html=rendered,
                    inbox_payload=inbox,
                    interactive_map_entry=ix_entry,
                    url_to_local=asset_result.url_to_local,
                    real_project_dir=output_dir,
                    llm=page_llm,
                    is_home=is_home,
                    slug_by_url=slug_by_url,
                    base_origin=base_origin,
                )
            except Exception as e:
                log.error(f"page generation failed for {slug}: {e}")
                result = {"slug": slug, "error": str(e)}
            page_results.append(result)

    # 8. Interaction wiring — AI-optional. Off by default; the deterministic
    # runtime covers 7 patterns (menu/modal/sticky/cookie/form-prevent/
    # purchase-warn/smooth-scroll) which is enough for most sites.
    slugs = [r.get("slug") for r in page_results if r.get("slug")]
    if ai_runtime and llm.backend != "mock":
        wire_stats = wire_interactions.run(interactive_map, slugs, output_dir, llm)
    else:
        # Direct path to the fallback runtime — no LLM call.
        from .wire_interactions import _fallback_runtime, WireStats
        fb = _fallback_runtime()
        js_dir = output_dir / "assets" / "js"
        js_dir.mkdir(parents=True, exist_ok=True)
        (js_dir / "runtime.js").write_text(fb["js"], encoding="utf-8")
        if fb["css"].strip():
            (css_dir / "runtime.css").write_text(fb["css"], encoding="utf-8")
        wire_stats = WireStats(
            js_bytes=len(fb["js"]),
            css_bytes=len(fb["css"]),
            patterns_wired=fb["patterns_wired"],
            patterns_skipped=fb["patterns_skipped_by_policy"],
            accepted=True,
            notes=["deterministic fallback (ai_runtime=False)"],
        )

    # 9. README
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    brand_primary = ((design_tokens.get("color") or {}).get("brand") or {}).get("primary") or {}
    brand_primary_val = brand_primary.get("value") if isinstance(brand_primary, dict) else None
    readme = env.get_template("README.md.j2").render(
        domain=domain,
        source_url=base_origin,
        generated_at=datetime.utcnow().isoformat(),
        capture_dir=str(capture_dir),
        output_dir=str(output_dir),
        brand_primary=brand_primary_val,
    )
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    # 10. Verify
    verify_report = None
    if not skip_verify and slugs:
        try:
            verify_report = verify.verify(output_dir, slugs)
        except Exception as e:
            log.warning(f"verify step failed: {e}")
            verify_report = {"error": str(e)}

    # 11. Final report
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "mode": mode,
        "capture_dir": str(capture_dir),
        "output_dir": str(output_dir),
        "domain": domain,
        "source_url": base_origin,
        "llm": {
            "backend": llm.backend,
            "mock": llm.mock,
            "model": llm.model,
            "usage": asdict(llm.usage) if llm.backend != "mock" else None,
            "cli_cost_usd": (llm._cli_client.usage.total_cost_usd if llm._cli_client else None),
        },
        "stages": {
            "css_extract": asdict(css_stats),
            "asset_rewrite": {
                "copied": asset_result.assets_copied,
                "bytes": asset_result.bytes_copied,
                "cross_origin_kept": len(asset_result.cross_origin_kept),
                "analytics_stripped": len(asset_result.analytics_stripped),
                "missing_local": len(asset_result.missing_local),
            },
            "css_consolidate": asdict(css_consolidate_stats),
            "pages_generated": len(page_results),
            "interactions": asdict(wire_stats),
        },
        "pages": page_results,
        "todos": [t for r in page_results for t in (r.get("todos") or [])],
        "notes": [n for r in page_results for n in (r.get("notes") or [])],
        "verify": verify_report,
        "duration_seconds": time.time() - t_start,
    }
    (output_dir / "normalize_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
