"""
Final reporting stage.

Renders REPORT.md from a Jinja template, prepares the local inspector
directory (rewrites HTML asset paths to local copies, generates index page),
and copies the inspector server into place for the user to launch.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from scripts.config import Config
from scripts.models import (
    AssetManifest,
    CaptureManifest,
    ContentInventory,
    DesignTokens,
    IATree,
    PageMeta,
    load_model,
)
from scripts.utils import (
    ensure_dir,
    relative_to_output,
    rewrite_html_asset_paths,
)


log = logging.getLogger(__name__)


def generate(
    config: Config,
    captures: CaptureManifest,
    assets: AssetManifest | None,
    tokens: DesignTokens,
    content: ContentInventory,
    ia: IATree,
    warnings: list[str],
) -> None:
    """Render REPORT.md and build inspector/."""
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))

    # 1. REPORT.md
    report_md = env.get_template("report.md.j2").render(
        config=config,
        captures=captures,
        assets=assets,
        tokens=tokens,
        content=content,
        ia=ia,
        warnings=warnings,
        generated_at=datetime.utcnow().isoformat(),
    )
    (config.output_dir / "REPORT.md").write_text(report_md, encoding="utf-8")

    # 2. Inspector
    _build_inspector(config, captures, assets, tokens, env)


def _build_inspector(
    config: Config,
    captures: CaptureManifest,
    assets: AssetManifest | None,
    tokens: DesignTokens,
    env: Environment,
) -> None:
    inspector_dir = ensure_dir(config.output_dir / "inspector")
    pages_dir = ensure_dir(inspector_dir / "pages")

    # Build url->local map for HTML rewriting
    url_to_local: dict[str, str] = {}
    if assets:
        for a in assets.assets:
            if a.download_status != "ok":
                continue
            # Rewrite to relative path FROM the inspector page (which lives at inspector/pages/)
            # raw/assets/images/abc.png  -->  ../../raw/assets/images/abc.png
            url_to_local[a.original_url] = f"../../{a.local_path}"

    # Copy a server-side index manifest the inspector reads at runtime
    index_entries = []
    for cap in captures.captures:
        if cap.status != "ok":
            continue
        rendered = (config.output_dir / cap.files.rendered_html).read_text(errors="ignore")
        rewritten = rewrite_html_asset_paths(rendered, url_to_local, cap.url)
        page_html_path = pages_dir / f"{cap.slug}.html"

        # Wrap rewritten page in inspector chrome
        wrapped = env.get_template("inspector_page.html.j2").render(
            page_html=rewritten,
            slug=cap.slug,
            url=cap.url,
        )
        page_html_path.write_text(wrapped, encoding="utf-8")

        meta = load_model(config.output_dir / cap.files.meta, PageMeta)
        screenshot = cap.files.screenshot_desktop
        index_entries.append({
            "slug": cap.slug,
            "url": cap.url,
            "title": meta.title,
            "html": f"pages/{cap.slug}.html",
            "screenshot": f"../{screenshot}",
        })

    # Index page
    index_html = env.get_template("inspector_index.html.j2").render(
        domain=config.domain,
        target_url=config.url,
        pages=index_entries,
    )
    (inspector_dir / "index.html").write_text(index_html, encoding="utf-8")

    # Tokens overlay (CSS variables + visual swatches)
    tokens_css = env.get_template("tokens.css.j2").render(tokens=tokens)
    (inspector_dir / "tokens.css").write_text(tokens_css, encoding="utf-8")

    # Write a JSON manifest for the JS-side inspector if a UI is added later
    (inspector_dir / "manifest.json").write_text(json.dumps({
        "domain": config.domain,
        "pages": index_entries,
    }, indent=2))

    log.info(f"Inspector built at {inspector_dir}")
