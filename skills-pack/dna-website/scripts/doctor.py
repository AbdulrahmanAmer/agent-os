"""
Environment validator. Run before reporting bugs.

Checks:
  - Python version
  - Required Python packages and versions
  - Playwright browsers installed
  - Node and required npm packages
  - Network access (DNS resolution works)
  - File permissions in expected directories

Outputs a colored report and exits with 0 if all green, 1 if any failure.
"""

from __future__ import annotations

import importlib.metadata
import shutil
import socket
import subprocess
import sys
from pathlib import Path

try:
    from rich.console import Console
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


# ---------------------------------------------------------------------------
# Required versions
# ---------------------------------------------------------------------------

MIN_PYTHON = (3, 11)

REQUIRED_PY_PACKAGES = {
    "playwright": "1.40",
    "beautifulsoup4": "4.12",
    "lxml": "5.0",
    "pydantic": "2.5",
    "typer": "0.9",
    "aiohttp": "3.9",
    "jinja2": "3.1",
    "scikit-learn": "1.4",
    "numpy": "1.26",
    "tldextract": "5.0",
    "tenacity": "8.2",
    "rich": "13.0",
    "python-dotenv": "1.0",
    "Pillow": "10.0",
    "colorthief": "0.2",
    "tinycss2": "1.2",
    "cssutils": "2.9",
}

REQUIRED_NODE_PACKAGES = ["express", "css-tree", "fontkit", "open", "chalk", "playwright"]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_python_version() -> tuple[bool, str]:
    if sys.version_info >= MIN_PYTHON:
        return True, f"{sys.version.split()[0]}"
    return False, f"{sys.version.split()[0]} < {MIN_PYTHON[0]}.{MIN_PYTHON[1]}"


def check_py_package(name: str, min_version: str) -> tuple[bool, str]:
    try:
        installed = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False, "not installed"
    if _version_ge(installed, min_version):
        return True, installed
    return False, f"{installed} < {min_version}"


def check_node() -> tuple[bool, str]:
    if not shutil.which("node"):
        return False, "node not in PATH"
    try:
        out = subprocess.check_output(["node", "--version"], text=True).strip()
        # v20.10.0 → 20.10.0
        version = out.lstrip("v")
        major = int(version.split(".")[0])
        if major < 18:
            return False, f"{version} < 18"
        return True, version
    except Exception as e:
        return False, str(e)


def check_node_package(name: str) -> tuple[bool, str]:
    pkg_root = Path(__file__).parent.parent / "node_modules" / name
    if pkg_root.exists():
        pkg_json = pkg_root / "package.json"
        if pkg_json.exists():
            import json
            try:
                data = json.loads(pkg_json.read_text())
                return True, data.get("version", "?")
            except Exception:
                return True, "(installed)"
        return True, "(installed)"
    return False, "not installed"


def check_playwright_browser() -> tuple[bool, str]:
    """Check whether Playwright Chromium is installed by inspecting the install dir."""
    try:
        out = subprocess.check_output(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            stderr=subprocess.STDOUT, text=True, timeout=10,
        )
        # Modern playwright prints 'Install location:' + a Chromium version.
        # Older versions said 'is already installed'.
        if "is already installed" in out or "Browser is already installed" in out:
            return True, "chromium installed"
        # Look for an "Install location" line that points to an existing path.
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Install location:"):
                path = line.split(":", 1)[1].strip()
                if path and Path(path).exists():
                    return True, f"chromium installed ({Path(path).name})"
        return False, "chromium may need install"
    except subprocess.CalledProcessError as e:
        return False, f"check failed: {e.output[:100]}"
    except Exception as e:
        return False, str(e)


def check_network() -> tuple[bool, str]:
    """Can we resolve DNS?"""
    try:
        socket.gethostbyname("anthropic.com")
        return True, "DNS ok"
    except Exception as e:
        return False, f"DNS failed: {e}"


def check_workspace_writable() -> tuple[bool, str]:
    """Can we write to the current directory?"""
    test = Path(".dna-doctor-test")
    try:
        test.write_text("ok")
        test.unlink()
        return True, "writable"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _version_ge(a: str, b: str) -> bool:
    """Crude semver comparison. Handles X.Y and X.Y.Z."""
    def parts(v: str) -> tuple[int, ...]:
        out = []
        for p in v.split("."):
            try:
                out.append(int(p.split("-")[0].split("+")[0]))
            except ValueError:
                out.append(0)
        return tuple(out)
    return parts(a) >= parts(b)


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    ok, msg = check_python_version()
    results.append(("Python ≥ 3.11", ok, msg))

    for name, ver in REQUIRED_PY_PACKAGES.items():
        ok, msg = check_py_package(name, ver)
        results.append((f"  py: {name} ≥ {ver}", ok, msg))

    ok, msg = check_node()
    results.append(("Node ≥ 18", ok, msg))

    for name in REQUIRED_NODE_PACKAGES:
        ok, msg = check_node_package(name)
        results.append((f"  node: {name}", ok, msg))

    ok, msg = check_playwright_browser()
    results.append(("Playwright (chromium)", ok, msg))

    ok, msg = check_network()
    results.append(("Network (DNS)", ok, msg))

    ok, msg = check_workspace_writable()
    results.append(("Workspace writable", ok, msg))

    # Print results
    failures = [name for name, ok, _ in results if not ok]

    if HAS_RICH:
        console = Console()
        table = Table(title="dna-website doctor", show_lines=False)
        table.add_column("Check")
        table.add_column("Status", style="bold")
        table.add_column("Detail")
        for name, ok, msg in results:
            status = "[green]✓[/green]" if ok else "[red]✗[/red]"
            table.add_row(name, status, msg)
        console.print(table)
        if failures:
            console.print(f"\n[red]{len(failures)} check(s) failed.[/red] See above.\n")
        else:
            console.print("\n[green]All checks passed.[/green]\n")
    else:
        for name, ok, msg in results:
            mark = "✓" if ok else "✗"
            print(f"  {mark} {name:40s} {msg}")
        if failures:
            print(f"\n{len(failures)} check(s) failed.")
        else:
            print("\nAll checks passed.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
