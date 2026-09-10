"""
Compare two dna-website runs.

Useful for:
  - Tracking how a site's design has evolved over time
  - Detecting regressions in the tool itself (run twice, diff outputs)
  - Reviewing the impact of an algorithm change

Usage:
    python -m scripts.compare <run-a> <run-b> [--out diff-report.md]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import typer

app = typer.Typer(add_completion=False)


@app.command()
def main(
    run_a: str = typer.Argument(..., help="Path to first run output dir"),
    run_b: str = typer.Argument(..., help="Path to second run output dir"),
    out: str = typer.Option("diff-report.md", "--out"),
) -> None:
    a, b = Path(run_a), Path(run_b)
    if not a.exists() or not b.exists():
        raise SystemExit(f"One or both run dirs missing: {a}, {b}")

    sections = []
    sections.append(_header(a, b))
    sections.append(_compare_pages(a, b))
    sections.append(_compare_tokens(a, b))
    sections.append(_compare_assets(a, b))
    sections.append(_compare_components(a, b))

    Path(out).write_text("\n\n".join(sections))
    print(f"Wrote diff to {out}")


def _header(a: Path, b: Path) -> str:
    return f"""# Run diff

- **A**: `{a}`
- **B**: `{b}`
- **Generated**: {datetime.utcnow().isoformat()}
"""


def _compare_pages(a: Path, b: Path) -> str:
    cap_a = _load(a / "captures.json")
    cap_b = _load(b / "captures.json")
    if not cap_a or not cap_b:
        return "## Pages\n_Missing captures.json in one or both runs._"

    urls_a = {c["url"] for c in cap_a["captures"] if c["status"] == "ok"}
    urls_b = {c["url"] for c in cap_b["captures"] if c["status"] == "ok"}

    added = urls_b - urls_a
    removed = urls_a - urls_b
    common = urls_a & urls_b

    lines = ["## Pages"]
    lines.append(f"- Common: {len(common)}")
    if added:
        lines.append(f"- **Added in B** ({len(added)}):")
        for u in sorted(added)[:30]:
            lines.append(f"  - `{u}`")
    if removed:
        lines.append(f"- **Removed in B** ({len(removed)}):")
        for u in sorted(removed)[:30]:
            lines.append(f"  - `{u}`")
    if not added and not removed:
        lines.append("_No page-level changes._")
    return "\n".join(lines)


def _compare_tokens(a: Path, b: Path) -> str:
    tok_a = _load(a / "analysis" / "design-tokens.json")
    tok_b = _load(b / "analysis" / "design-tokens.json")
    if not tok_a or not tok_b:
        return "## Design tokens\n_Missing design-tokens.json in one or both runs._"

    lines = ["## Design tokens"]

    # Colors
    primary_a = (tok_a.get("color", {}).get("brand", {}).get("primary") or {}).get("value")
    primary_b = (tok_b.get("color", {}).get("brand", {}).get("primary") or {}).get("value")
    if primary_a != primary_b:
        lines.append(f"- Brand primary: `{primary_a}` → `{primary_b}`")

    # Neutrals
    neutrals_a = {k: v.get("value") for k, v in (tok_a.get("color", {}).get("neutrals") or {}).items()}
    neutrals_b = {k: v.get("value") for k, v in (tok_b.get("color", {}).get("neutrals") or {}).items()}
    for k in sorted(set(neutrals_a) | set(neutrals_b)):
        if neutrals_a.get(k) != neutrals_b.get(k):
            lines.append(f"- Neutral `{k}`: `{neutrals_a.get(k)}` → `{neutrals_b.get(k)}`")

    # Type scale
    ratio_a = (tok_a.get("typography", {}).get("scale") or {}).get("ratio")
    ratio_b = (tok_b.get("typography", {}).get("scale") or {}).get("ratio")
    if ratio_a != ratio_b:
        lines.append(f"- Type scale ratio: `{ratio_a}` → `{ratio_b}`")

    # Spacing base
    sp_a = (tok_a.get("spacing") or {}).get("base_unit_px")
    sp_b = (tok_b.get("spacing") or {}).get("base_unit_px")
    if sp_a != sp_b:
        lines.append(f"- Spacing base: `{sp_a}` → `{sp_b}`")

    if len(lines) == 1:
        lines.append("_No token changes detected._")
    return "\n".join(lines)


def _compare_assets(a: Path, b: Path) -> str:
    ast_a = _load(a / "asset_manifest.json")
    ast_b = _load(b / "asset_manifest.json")
    if not ast_a or not ast_b:
        return "## Assets\n_Missing asset_manifest.json in one or both runs._"

    hashes_a = {x["content_hash"] for x in ast_a["assets"] if x["content_hash"]}
    hashes_b = {x["content_hash"] for x in ast_b["assets"] if x["content_hash"]}

    lines = ["## Assets"]
    lines.append(f"- A: {len(hashes_a)} unique, B: {len(hashes_b)} unique")
    lines.append(f"- Added in B: {len(hashes_b - hashes_a)}")
    lines.append(f"- Removed in B: {len(hashes_a - hashes_b)}")
    return "\n".join(lines)


def _compare_components(a: Path, b: Path) -> str:
    cmp_a = _load(a / "analysis" / "component-patterns.json")
    cmp_b = _load(b / "analysis" / "component-patterns.json")
    if not cmp_a or not cmp_b:
        return "## Components\n_Missing component-patterns.json in one or both runs._"

    pats_a = {(p["role_guess"], len(p["common_classes"])): p["occurrence_count"]
              for p in cmp_a.get("patterns", [])}
    pats_b = {(p["role_guess"], len(p["common_classes"])): p["occurrence_count"]
              for p in cmp_b.get("patterns", [])}

    lines = ["## Components"]
    lines.append(f"- A: {len(pats_a)} patterns, B: {len(pats_b)} patterns")

    # Show role-level summary
    roles_a = {}
    roles_b = {}
    for p in cmp_a.get("patterns", []):
        roles_a[p["role_guess"]] = roles_a.get(p["role_guess"], 0) + p["occurrence_count"]
    for p in cmp_b.get("patterns", []):
        roles_b[p["role_guess"]] = roles_b.get(p["role_guess"], 0) + p["occurrence_count"]
    for role in sorted(set(roles_a) | set(roles_b)):
        if roles_a.get(role, 0) != roles_b.get(role, 0):
            lines.append(f"- `{role}`: {roles_a.get(role, 0)} → {roles_b.get(role, 0)}")

    return "\n".join(lines)


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


if __name__ == "__main__":
    app()
