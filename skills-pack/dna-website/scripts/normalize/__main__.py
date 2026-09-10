"""
CLI entry point for the dna-website normalizer.

Usage:
   python -m scripts.normalize --capture outputs/kindskiptracing-2026-05-11-v2 \
                               --output real-projects/kindskiptracing-com

Env vars consumed:
   ANTHROPIC_API_KEY        - required for live AI calls
   DNA_LLM_MODEL            - override the model (default: claude-sonnet-4-6)
   DNA_LLM_MAX_TOKENS       - override max output tokens (default: 8000)
   DNA_NORMALIZE_MOCK_LLM=1 - skip the AI calls; use deterministic
                              fallbacks (test/dry-run mode)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="scripts.normalize",
        description="Convert a dna-website capture into a real HTML/CSS/JS project.",
    )
    ap.add_argument("--capture", required=True, help="Path to a dna-website capture dir (e.g. outputs/<host>-<date>)")
    ap.add_argument("--output", required=True, help="Where to write the real-project (will be created/overwritten)")
    ap.add_argument("--only", nargs="+", help="Process only these slugs (default: all)")
    ap.add_argument("--skip-verify", action="store_true", help="Skip the headless-browser smoke test")
    ap.add_argument("--mode", choices=["preserve", "rewrite"], default="preserve",
                    help="preserve (default): keep original DOM/CSS verbatim, strip only the SPA runtime. "
                         "rewrite: AI rewrites each page into clean semantic HTML5 using design tokens.")
    ap.add_argument("--mock", action="store_true", help="Use deterministic fallbacks for ALL stages (no LLM calls)")
    ap.add_argument("--no-ai-pages", action="store_true",
                    help="(rewrite mode only) Disable AI for per-page HTML")
    ap.add_argument("--ai-css", action="store_true",
                    help="(rewrite mode only) Use AI to consolidate base.css")
    ap.add_argument("--ai-runtime", action="store_true",
                    help="(rewrite mode only) Use AI to build runtime.js")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.mock:
        os.environ["DNA_NORMALIZE_MOCK_LLM"] = "1"

    capture = Path(args.capture).resolve()
    if not capture.exists():
        print(f"ERROR: capture dir not found: {capture}", file=sys.stderr)
        return 2

    # Validate the capture has the bits we need
    required = ("captures.json", "asset_manifest.json", "raw/pages")
    missing = [r for r in required if not (capture / r).exists()]
    if missing:
        print(f"ERROR: capture is incomplete; missing: {missing}", file=sys.stderr)
        print("Re-run scripts.bulk_capture and scripts.build_manifests first.", file=sys.stderr)
        return 2

    output = Path(args.output).resolve()

    from .orchestrator import run as run_pipeline
    report = run_pipeline(
        capture, output,
        only_slugs=args.only,
        skip_verify=args.skip_verify,
        mode=args.mode,
        ai_pages=not args.no_ai_pages,
        ai_css=args.ai_css,
        ai_runtime=args.ai_runtime,
    )

    stages = report["stages"]
    verify_stats = (report.get("verify") or {}).get("stats") if report.get("verify") else None

    print()
    print("=" * 72)
    print(f"Normalized into {output}")
    print("=" * 72)
    backend = report['llm']['backend']
    label = {"mock": "MOCK (deterministic fallbacks)",
             "cli":  f"CLI (claude --print, model={report['llm']['model']})",
             "sdk":  f"SDK (anthropic, model={report['llm']['model']})"}.get(backend, backend)
    print(f"  Mode          : {report.get('mode', 'preserve')}")
    print(f"  LLM backend   : {label}")
    if report['llm'].get("usage"):
        u = report['llm']['usage']
        cost = report['llm'].get('cli_cost_usd')
        cost_str = f"  ~${cost:.2f}" if cost else ""
        print(f"  LLM calls     : {u['calls']}  in/out: {u['input_tokens']}/{u['output_tokens']}  cache read/create: {u['cache_read_tokens']}/{u['cache_create_tokens']}{cost_str}")
    print(f"  Pages         : {stages['pages_generated']}")
    print(f"  Assets copied : {stages['asset_rewrite']['copied']} ({stages['asset_rewrite']['bytes']/1024:.0f} KB)")
    print(f"  Base/Comp CSS : {stages['css_consolidate']['base_bytes']} / {stages['css_consolidate']['components_bytes']} bytes")
    print(f"  Runtime JS    : {stages['interactions']['js_bytes']} bytes ({len(stages['interactions']['patterns_wired'])} patterns)")
    if verify_stats:
        print(f"  Verify        : {verify_stats.get('passed',0)}/{verify_stats.get('pages',0)} passed  "
              f"console-errors={verify_stats.get('total_console_errors',0)}  "
              f"failed-requests={verify_stats.get('total_failed_requests',0)}")
    print(f"  Duration      : {report['duration_seconds']:.1f}s")
    print()
    print(f"Open in VS Code: code {output}")
    print(f"Or preview:      python -m http.server -d {output} 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
