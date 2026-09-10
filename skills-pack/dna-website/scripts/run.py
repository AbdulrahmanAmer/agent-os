"""
Orchestrator. Runs the full pipeline end-to-end.

Usage:
    python -m scripts.run <url> [options]

The orchestrator is intentionally thin — it only sequences stages and writes
the final manifest. Each stage handles its own concerns and writes its own
artifacts to disk. This makes the pipeline resumable and testable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler

from scripts import (
    analyze_content,
    analyze_dna,
    auth as auth_module,
    build_rebrand,
    crawl,
    discover,
    download_assets,
    preflight,
    report,
)
from scripts.config import Config, build_config
from scripts.models import (
    RunFiles,
    RunManifest,
    RunStats,
    write_model,
)
from scripts.utils import ensure_dir


app = typer.Typer(add_completion=False)
console = Console()


def _setup_logging(output_dir: Path, verbose: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "run.log"

    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    rich_handler = RichHandler(console=console, rich_tracebacks=True, show_path=False)

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[rich_handler, file_handler],
    )


@app.command()
def main(
    url: str = typer.Argument(..., help="Target URL (must include scheme)"),
    auth: str | None = typer.Option(None, "--auth", help="Auth profile name"),
    depth: int = typer.Option(
        4, "--depth",
        help="Max BFS crawl depth (default 4). Pass 0 for UNLIMITED — every "
             "reachable level. Use 0 for true full-capture runs.",
    ),
    max_pages: int = typer.Option(
        200, "--max-pages",
        help="Hard cap on number of pages (default 200). Pass 0 for "
             "UNLIMITED — the crawl finishes when the BFS frontier is empty.",
    ),
    max_asset_size: int = typer.Option(50, "--max-asset-size", help="MB"),
    include_subdomains: bool = typer.Option(False, "--include-subdomains"),
    skip_assets: bool = typer.Option(False, "--skip-assets"),
    mobile_also: bool = typer.Option(False, "--mobile-also"),
    output: str | None = typer.Option(None, "--output"),
    resume: bool = typer.Option(False, "--resume"),
    ignore_robots: bool = typer.Option(False, "--ignore-robots"),
    i_own_this_site: bool = typer.Option(False, "--i-own-this-site"),
    rate_limit: float = typer.Option(2.0, "--rate-limit"),
    concurrency: int = typer.Option(3, "--concurrency"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Crawl a website and produce a DNA package."""
    started = time.time()
    started_at = datetime.utcnow()

    # Phase A: build config
    config = build_config(
        url,
        auth=auth,
        depth=depth,
        max_pages=max_pages,
        max_asset_size_mb=max_asset_size,
        include_subdomains=include_subdomains,
        skip_assets=skip_assets,
        mobile_also=mobile_also,
        output=output,
        resume=resume,
        ignore_robots=ignore_robots,
        i_own_this_site=i_own_this_site,
        rate_limit=rate_limit,
        concurrency=concurrency,
        verbose=verbose,
    )
    ensure_dir(config.output_dir)
    _setup_logging(config.output_dir, verbose)
    log = logging.getLogger("run")
    log.info(f"DNA-website starting for {config.url}")
    log.info(f"Output dir: {config.output_dir}")

    warnings: list[str] = []

    # Phase B: preflight
    log.info("[1/8] Preflight checks...")
    preflight_result = preflight.run_preflight(config)
    warnings.extend(preflight_result.warnings)

    # Phase C: auth (optional)
    session_path: Path | None = None
    if config.auth_profile is not None:
        log.info("[2/8] Authenticating via Chrome MCP / Playwright...")
        session_path = asyncio.run(auth_module.login(config))
        log.info(f"Session saved: {session_path}")
    else:
        log.info("[2/8] No --auth; skipping login.")

    # Phase D: discovery
    log.info("[3/8] Discovering routes...")
    routes = asyncio.run(discover.find_routes(config, session_path))
    log.info(f"Discovered {len(routes.routes)} routes")

    # Phase E: crawl
    log.info("[4/8] Crawling pages...")
    captures = asyncio.run(crawl.capture_all(config, routes, session_path))
    log.info(f"Captured {captures.successful}/{captures.total} pages")
    warnings.extend([
        f"Page capture failed: {c.url}" for c in captures.captures if c.status == "error"
    ])

    # Phase F: assets
    if not config.skip_assets:
        log.info("[5/8] Downloading assets...")
        assets = asyncio.run(download_assets.fetch_all(config, captures, session_path))
        log.info(
            f"Downloaded {assets.stats.total - assets.stats.failed}/{assets.stats.total} assets"
        )
    else:
        log.info("[5/8] --skip-assets set; skipping asset download.")
        assets = None

    # Phase G: DNA analysis
    log.info("[6/8] Analyzing design DNA...")
    tokens = analyze_dna.run(config)

    # Phase H: content analysis
    log.info("[7/8] Building content inventory + IA...")
    content_inv, ia = analyze_content.run(config, captures)

    # Phase I: rebrand
    log.info("[8/8] Building rebrand layer + final report...")
    build_rebrand.run(config, tokens, content_inv)

    # Phase J: report + inspector
    report.generate(config, captures, assets, tokens, content_inv, ia, warnings)

    duration = time.time() - started

    # Write final manifest
    manifest = RunManifest(
        target_url=config.url,
        base_origin=config.base_origin,
        domain=config.domain,
        output_dir=str(config.output_dir),
        started_at=started_at,
        completed_at=datetime.utcnow(),
        duration_seconds=duration,
        flags={
            "auth": auth,
            "depth": depth,
            "max_pages": max_pages,
            "include_subdomains": include_subdomains,
            "skip_assets": skip_assets,
            "mobile_also": mobile_also,
            "ignore_robots": ignore_robots,
            "i_own_this_site": i_own_this_site,
        },
        stats=RunStats(
            pages_crawled=captures.successful,
            pages_failed=captures.failed,
            assets_downloaded=(assets.stats.total - assets.stats.failed) if assets else 0,
            assets_failed=assets.stats.failed if assets else 0,
            total_bytes=assets.stats.total_bytes if assets else 0,
            unique_colors=len(tokens.color.raw_clusters) if tokens else 0,
            unique_fonts=len(tokens.typography.families) if tokens else 0,
            component_patterns_detected=0,  # filled in by analyze_dna; TODO
        ),
        files=RunFiles(),
        warnings=warnings,
    )
    write_model(config.output_dir / "manifest.json", manifest)

    console.print()
    console.print(f"[bold green]✓ Done in {duration:.1f}s[/bold green]")
    console.print(f"  Report:    [link]{config.output_dir / 'REPORT.md'}[/link]")
    console.print(f"  Inspector: cd {config.output_dir} && node ../../node_helpers/inspector_server.mjs inspector")
    console.print(f"  Rebrand:   {config.output_dir / 'rebrand' / 'tokens.template.json'}")


if __name__ == "__main__":
    app()
