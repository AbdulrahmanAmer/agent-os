#!/usr/bin/env python3
"""Builds dist/agent-os-<version>.zip - the drop-in bundle.

The zip contains a single top-level `.agent-os/` folder, so extracting it at a project root gives
that project the whole system and nothing else. Version comes from plugin/.claude-plugin/plugin.json
so the zip can never disagree with the plugin manifest.

Run: python build-bundle.py
"""
import io
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "plugin")
SKILLS = os.path.join(ROOT, "skills-pack")
DIST = os.path.join(ROOT, "dist")

# What ships. Anything not listed is deliberately absent - a bundle that carries a stray venv or a
# previous project's outputs is how a 36 MB folder becomes 559 MB.
INCLUDE_DIRS = ["layers", "scripts", "hooks"]
SKIP_NAMES = {"__pycache__", ".venv", "node_modules", ".pytest_cache", ".git"}
SKIP_SUFFIX = (".pyc", ".pyo")

# The skills the router points at travel with it. They live OUTSIDE plugin/ on purpose: inside it
# they would auto-load in every project the plugin is installed in, and pay their always-on
# description cost even in projects that never use them. Here they are copied into a project's own
# .claude/skills/ by install.py, so the cost is per-project and opted into.
SKILLS_ARC = ".agent-os/skills/"


def add(zf, full, arc):
    """Write one file, preserving the unix executable bit for shell scripts.

    zipfile.write() records the source file's mode, and on Windows that is 0o666 for everything.
    Extracted on macOS or Linux the hooks then arrive without +x and the harness cannot run them -
    a bundle that works perfectly on the machine that built it and silently does nothing anywhere
    else. Shell scripts are forced to 0o755 here so the archive is honest about what is executable.
    """
    info = zipfile.ZipInfo.from_file(full, arc)
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = 0o755 if arc.endswith(".sh") else 0o644
    info.external_attr = (mode << 16) | (info.external_attr & 0xFFFF)
    with open(full, "rb") as fh:
        zf.writestr(info, fh.read())


def version():
    with open(os.path.join(SRC, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
        return json.load(fh)["version"]


def walk(base, arc_prefix, arc_root):
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES]
        for name in sorted(filenames):
            if name.endswith(SKIP_SUFFIX) or name in SKIP_NAMES:
                continue
            full = os.path.join(dirpath, name)
            out.append((full, arc_prefix + os.path.relpath(full, arc_root).replace("\\", "/")))
    return out


def collect():
    out = []
    for top in INCLUDE_DIRS:
        out += walk(os.path.join(SRC, top), ".agent-os/", SRC)
    if os.path.isdir(SKILLS):
        out += walk(SKILLS, SKILLS_ARC, SKILLS)
    return sorted(out, key=lambda pair: pair[1])


LICENSE = """MIT License

Copyright (c) 2026 Abdulrahman Amer

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT
OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

This licence covers agent-os itself: layers/, scripts/, hooks/. It does NOT cover anything under
skills/ - see NOTICE.
"""

NOTICE = """THIRD-PARTY CONTENT - read before redistributing this bundle.

The `skills/` directory carries work that is NOT ours. Most of it came from third-party skill
packs and plugins, and 14 of the 15 skills declare no licence of their own.

That is fine for your own machines. It is NOT automatically fine for shipping to other people.
Before distributing a bundle that includes skills/, either:

  - confirm each skill's upstream licence permits redistribution and record it here, or
  - build the core-only bundle instead:  python build-bundle.py --core

The core bundle contains only agent-os itself, which is MIT and yours to ship. Its installer works
identically; it simply reports "skills: none in this bundle" and installs the adapters.
"""

README = """# agent-os - drop-in bundle

Extract at the root of any project. You get one folder, `.agent-os/`, and nothing else.

    python .agent-os/scripts/install.py

That detects the harness and wires the strongest adapter it supports, then tells you what it did.

## What this gives the project

A **stage**, and a context layer that loads only that stage. The project declares its own stage in
a state file (`.agent-os/STATE.md` or `PROJECT-STATE.md`):

    STAGE: 0
    enforcement: deny      # deny | warn | off

No state file means nothing is enforced. Not a default of stage 0 - nothing. Create one with:

    python .agent-os/scripts/agent_os.py init

## What is portable and what is not

The content (`layers/`) and the CLI (`scripts/agent_os.py`) are plain markdown and dependency-free
python. They run under any harness, or none.

Enforcement is different, because a gate needs the harness to ask permission before it writes:

| harness | what you get |
|---|---|
| Claude Code | REAL. Hooks deny a stage-forbidden edit before it happens, inject the stage context at session start, and block a stage-advance claim the state file never recorded. |
| Codex CLI | ADVISORY. Context is rendered into `AGENTS.md`, which Codex reads. It has no pre-write hook, so the stage instructs rather than stops. |
| opencode | ADVISORY, same mechanism. |
| git | REAL, and harness-independent. A pre-commit hook runs the gate over staged files and refuses the commit. This is the backstop for the advisory cases. |

Install the git backstop alongside an advisory harness and you get enforcement even when the agent
ignores its instructions:

    python .agent-os/scripts/install.py --harness codex git

## Commands

    agent_os.py context            print the current stage's context (any harness, no hooks)
    agent_os.py check <path>...    the gate as a command - exit 1 if the stage forbids a path
    agent_os.py stage              what stage is this project in
    agent_os.py stage 1            advance it
    agent_os.py init               write a state file

After changing the stage, re-render the advisory blocks:

    python .agent-os/scripts/install.py --refresh

## The stages

| # | stage | ends when |
|---|---|---|
| 0 | SHAPE | every open decision is answered in writing |
| 1 | DESIGN DIRECTION | a winner picked from rendered options, written down as tokens |
| 2 | SYSTEM DESIGN | the plan exists, is read, and is sliced with verifiable exits |
| 3 | BUILD | every slice closed and verified as it landed |
| 4 | HARDEN | the demo-ware list is clean and there is a rollback path |
| 5 | LAUNCH AND ITERATE | verified live, watched, next slice chosen deliberately |

Stages 0 to 2 deny writes to `src/`, migrations and framework config; 3 to 5 deny nothing, because
by then sequencing is the plan's job. The rules are data, in `layers/stages.json` - edit them for
a project whose sequence differs.
"""


def main():
    core_only = "--core" in sys.argv
    ver = version()
    if not os.path.isdir(DIST):
        os.makedirs(DIST)
    name = "agent-os-core-%s.zip" if core_only else "agent-os-%s.zip"
    target = os.path.join(DIST, name % ver)
    files = collect()
    if core_only:
        files = [(full, arc) for full, arc in files if not arc.startswith(SKILLS_ARC)]
    if not files:
        raise SystemExit("nothing collected - refusing to write an empty bundle")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for full, arc in files:
            add(zf, full, arc)
        zf.writestr(".agent-os/README.md", README)
        zf.writestr(".agent-os/LICENSE", LICENSE)
        if any(arc.startswith(SKILLS_ARC) for _, arc in files):
            zf.writestr(".agent-os/NOTICE", NOTICE)

    size = os.path.getsize(target)
    skills = sorted({arc.split("/")[2] for _, arc in files if arc.startswith(SKILLS_ARC)})
    core = [arc for _, arc in files if not arc.startswith(SKILLS_ARC)]
    print("wrote %s" % target)
    print("%d files, %.0f KB" % (len(files) + 1, size / 1024.0))
    print()
    print("core (%d):" % (len(core) + 1))
    for arc in core:
        print("  " + arc)
    print("  .agent-os/README.md")
    print()
    print("skills (%d):" % len(skills))
    for name in skills:
        print("  " + name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
