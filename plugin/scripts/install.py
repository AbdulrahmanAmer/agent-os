#!/usr/bin/env python3
"""agent-os installer. Run from a project root after extracting the bundle:

    python .agent-os/scripts/install.py            # detect the harness and wire it
    python .agent-os/scripts/install.py --harness claude codex opencode
    python .agent-os/scripts/install.py --refresh  # re-render the injected blocks after a stage change

WHAT TRAVELS AND WHAT DOES NOT - read this before believing any claim of portability.

The CONTENT (layers/) and the CLI (scripts/agent_os.py) are harness-agnostic: plain markdown and
dependency-free python. They work anywhere.

ENFORCEMENT is not portable, because a gate needs the harness to ask permission before it writes.
So each harness gets the strongest adapter it can actually support:

  claude    REAL enforcement. Project-local hooks in .claude/settings.json: SessionStart injects
            the current stage's context, PreToolUse DENIES an edit the stage forbids, Stop blocks
            a stage-advance claim that never reached the state file.

  codex     ADVISORY. Codex CLI reads AGENTS.md at the repo root, so the context is rendered into
            a delimited block there. Codex has no pre-write permission hook, so the stage cannot
            physically stop a write - it is instruction, plus `agent_os.py check` which Codex can
            be told to run, and which a git pre-commit hook runs whether it cooperates or not.

  opencode  ADVISORY, same mechanism: AGENTS.md.

  git       REAL enforcement, harness-independent: a pre-commit hook that runs `check` over the
            staged paths and refuses the commit. This is the backstop that works even when the
            agent ignores everything else. Installed by --harness git.

Every injected block is delimited by sentinels and rewritten in place, so --refresh is idempotent
and never duplicates or clobbers the operator's own text.
"""
import json
import os
import shutil
import subprocess
import sys

BEGIN = "<!-- BEGIN agent-os (generated - edit .agent-os/layers/, not here) -->"
END = "<!-- END agent-os -->"

HERE = os.path.dirname(os.path.abspath(__file__))
PAYLOAD = os.path.dirname(HERE)  # the .agent-os directory
CLI = os.path.join(HERE, "agent_os.py")


def rel_from(root, path):
    return os.path.relpath(path, root).replace("\\", "/")


def render_context(root):
    """Ask the CLI for the current context block. One source of truth, no second renderer."""
    try:
        out = subprocess.run([sys.executable, CLI, "context"], cwd=root,
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip()
    except Exception as exc:
        return "agent-os could not render context: %s" % exc


def splice(existing, block):
    """Replace the delimited block, or append it. Never touches anything outside the sentinels."""
    payload = BEGIN + "\n\n" + block + "\n\n" + END
    if BEGIN in existing and END in existing:
        head = existing.split(BEGIN)[0]
        tail = existing.split(END, 1)[1]
        return head + payload + tail
    if existing.strip():
        return existing.rstrip() + "\n\n" + payload + "\n"
    return payload + "\n"


def write(path, text):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


# --------------------------------------------------------------------------- adapters


def install_claude(root):
    """Project-local hooks. Merges into an existing settings.json instead of overwriting it."""
    settings_path = os.path.join(root, ".claude", "settings.json")
    settings = {}
    if os.path.isfile(settings_path):
        try:
            settings = json.loads(read(settings_path)) or {}
        except ValueError:
            return "SKIPPED .claude/settings.json - it does not parse as JSON; fix it and re-run"

    prefix = rel_from(root, PAYLOAD)
    hooks = settings.setdefault("hooks", {})
    wanted = {
        "SessionStart": ("startup|resume|clear|compact", "session-start.sh", 20),
        "PreToolUse": ("Write|Edit|MultiEdit|NotebookEdit", "pre-tool-use.sh", 15),
        "Stop": (None, "stop.sh", 20),
    }
    added = []
    for event, (matcher, script, timeout) in wanted.items():
        command = '"$CLAUDE_PROJECT_DIR"/%s/hooks/%s' % (prefix, script)
        entries = hooks.setdefault(event, [])
        # Compare the command STRINGS. Comparing against json.dumps(entry) looks equivalent and is
        # not: dumps escapes the quotes inside the command, so the needle never matches and every
        # run appends another copy of the same hook.
        already = any(
            hook.get("command") == command
            for entry in entries if isinstance(entry, dict)
            for hook in entry.get("hooks", []) if isinstance(hook, dict))
        if already:
            continue
        entry = {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
        if matcher:
            entry["matcher"] = matcher
        entries.append(entry)
        added.append(event)

    write(settings_path, json.dumps(settings, indent=2) + "\n")
    if not added:
        return "claude: hooks already present in .claude/settings.json (nothing to add)"
    return "claude: REAL enforcement wired - added %s to .claude/settings.json" % ", ".join(added)


def install_agents_md(root, label):
    """Codex and opencode both read AGENTS.md at the repo root. Advisory, not enforced."""
    path = os.path.join(root, "AGENTS.md")
    block = render_context(root)
    write(path, splice(read(path), block))
    return ("%s: ADVISORY context written into AGENTS.md (%d chars). No pre-write hook exists in "
            "that harness, so run --refresh after a stage change, and install the git backstop for "
            "actual enforcement." % (label, len(block)))


def install_skills(root):
    """Copy the bundled skills into the project's own .claude/skills/.

    Never overwrites: a skill the project already has is left exactly as it is, because the local
    copy may have been edited for that project and silently replacing it would be the worst kind of
    installer behaviour. Reports what it skipped.
    """
    src = os.path.join(PAYLOAD, "skills")
    if not os.path.isdir(src):
        return "skills: none in this bundle"
    dest_root = os.path.join(root, ".claude", "skills")
    copied, skipped = [], []
    for name in sorted(os.listdir(src)):
        source = os.path.join(src, name)
        if not os.path.isdir(source):
            continue
        dest = os.path.join(dest_root, name)
        if os.path.exists(dest):
            skipped.append(name)
            continue
        shutil.copytree(source, dest)
        copied.append(name)
    msg = "skills: copied %d into .claude/skills/" % len(copied)
    if skipped:
        msg += " (left %d already present untouched: %s)" % (len(skipped), ", ".join(skipped))
    return msg


def install_git(root):
    """The one enforcement path that does not depend on the agent cooperating."""
    hooks_dir = os.path.join(root, ".git", "hooks")
    if not os.path.isdir(hooks_dir):
        return "git: SKIPPED - no .git/hooks (not a git repository)"
    path = os.path.join(hooks_dir, "pre-commit")
    existing = read(path)
    marker = "agent-os stage gate"
    if marker in existing:
        return "git: pre-commit hook already installed"
    cli = rel_from(root, CLI)
    lines = [
        "#!/bin/sh",
        "# " + marker + " - refuses a commit that the current stage forbids.",
        "files=$(git diff --cached --name-only --diff-filter=ACM)",
        '[ -z "$files" ] && exit 0',
        "# Find an interpreter. `python` does not exist on many macOS and Linux boxes, where it is",
        "# `python3`; assuming one name is how this hook dies silently on someone else's machine.",
        "PY=",
        "for c in python3 python py; do",
        '  command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }',
        "done",
        '[ -z "$PY" ] && exit 0   # no python: fail open rather than block every commit',
        '"$PY" "%s" check $files >/dev/null || exit 1' % cli,
        "exit 0",
        "",
    ]
    body = "\n".join(lines)
    if existing.strip():
        return ("git: SKIPPED - .git/hooks/pre-commit already exists and is not ours. Add this "
                "line to it yourself:\n    python \"%s\" check $(git diff --cached --name-only)" % cli)
    write(path, body)
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass
    return "git: REAL enforcement wired - .git/hooks/pre-commit refuses stage-forbidden commits"


# --------------------------------------------------------------------------- detection


def detect(root):
    found = []
    if os.path.isdir(os.path.join(root, ".claude")):
        found.append("claude")
    if os.path.isdir(os.path.join(root, ".codex")) or os.path.isfile(os.path.join(root, "AGENTS.md")):
        found.append("codex")
    if (os.path.isdir(os.path.join(root, ".opencode"))
            or os.path.isfile(os.path.join(root, "opencode.json"))
            or os.path.isfile(os.path.join(root, "opencode.jsonc"))):
        found.append("opencode")
    if os.path.isdir(os.path.join(root, ".git")):
        found.append("git")
    return found


def main():
    argv = sys.argv[1:]
    root = os.getcwd()
    refresh = "--refresh" in argv
    argv = [a for a in argv if a != "--refresh"]

    if "--harness" in argv:
        targets = argv[argv.index("--harness") + 1:]
    else:
        targets = detect(root)
        if not targets:
            targets = ["codex"]  # AGENTS.md is the widest-compatibility fallback
        print("detected: %s" % ", ".join(targets))

    if not os.path.isfile(CLI):
        print("agent_os.py not found next to install.py - is the bundle extracted intact?")
        return 1

    print("project: %s" % root)
    print("payload: %s" % rel_from(root, PAYLOAD))
    print()

    for target in targets:
        if target == "claude":
            print(" ", install_claude(root))
            print(" ", install_skills(root))
        elif target in ("codex", "opencode"):
            print(" ", install_agents_md(root, target))
        elif target == "git":
            print(" ", install_git(root))
        elif target == "skills":
            print(" ", install_skills(root))
        else:
            print("  unknown harness: %s" % target)

    state = None
    for candidate in (".agent-os/STATE.md", "PROJECT-STATE.md", "docs/PROJECT-STATE.md",
                      ".claude/PROJECT-STATE.md"):
        if os.path.isfile(os.path.join(root, candidate)):
            state = candidate
            break

    print()
    if state:
        print("state file: %s" % state)
    elif not refresh:
        print("no state file yet - nothing is enforced until one exists.")
        print("  python %s init" % rel_from(root, CLI))
    return 0


if __name__ == "__main__":
    sys.exit(main())
