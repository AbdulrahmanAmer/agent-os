"""
Thin Python wrapper that spawns the Node inspector server.

Used for convenience — `python -m scripts.serve <output-dir>` is shorter than
`node node_helpers/inspector_server.mjs <output-dir>/inspector`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer

app = typer.Typer(add_completion=False)


@app.command()
def main(
    output_dir: str = typer.Argument(..., help="Path to a dna-output/<run> directory"),
    port: int = typer.Option(7777, "--port"),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
) -> None:
    out = Path(output_dir).resolve()
    inspector = out / "inspector"
    if not inspector.exists():
        raise SystemExit(f"No inspector at {inspector}. Did the crawl finish?")
    server_script = Path(__file__).parent.parent / "node_helpers" / "inspector_server.mjs"
    env = os.environ.copy()
    env["INSPECTOR_PORT"] = str(port)
    if not open_browser:
        env["INSPECTOR_NO_OPEN"] = "1"
    print(f"Starting inspector at http://localhost:{port}")
    subprocess.run(["node", str(server_script), str(inspector)], env=env, check=False)


if __name__ == "__main__":
    app()
