#!/usr/bin/env python3
"""agent-os CLI. All plugin logic lives here; the hooks are thin shims that call it.

Subcommands (each reads the hook's JSON payload on stdin where relevant):
  context   SessionStart  -> print the layered context for the CURRENT stage only
  gate      PreToolUse    -> allow / deny an edit the current stage forbids (Claude Code JSON)
  settle    Stop          -> block a stage-advance claim that never reached the state file
  check <path>...         -> the same gate for any other harness: exit 1 if a path is denied
  init                    -> write a state file into the current project
  stage [n]               -> print the stage, or set it

`context` and `check` need no hook system and no stdin, which is what makes this usable outside
Claude Code: any harness can print the context and call the gate.

Design rules, in order of priority:
  1. FAIL OPEN. Any error, any missing file, any unparseable payload: exit 0, allow, print nothing.
     A context plugin that blocks a session is worse than no plugin.
  2. LOAD ONLY THE CURRENT STAGE. Stage 5's contract is noise during stage 0 (ICM anti-pattern).
  3. NEVER GUESS THE STAGE. No state file means no enforcement, not a default of zero.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
LAYERS = os.path.join(PLUGIN, "layers")

# Where a project may keep its state file, in priority order. First hit wins.
STATE_CANDIDATES = [
    ".agent-os/STATE.md",
    "PROJECT-STATE.md",
    "docs/PROJECT-STATE.md",
    ".claude/PROJECT-STATE.md",
]

STAGE_RE = re.compile(r"^\s*#{0,3}\s*\**\s*STAGE\s*:?\s*\**\s*(\d+)", re.I | re.M)
ENFORCE_RE = re.compile(r"^\s*enforcement\s*:\s*(deny|warn|off)\s*$", re.I | re.M)


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def stdin_payload():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def project_root(payload):
    for key in ("cwd", "project_dir", "projectDir"):
        val = payload.get(key)
        if val and os.path.isdir(val):
            return val
    return os.getcwd()


def find_state(root):
    for rel in STATE_CANDIDATES:
        path = os.path.join(root, rel)
        if os.path.isfile(path):
            return path
    return None


def load_stages():
    try:
        with open(os.path.join(LAYERS, "stages.json"), encoding="utf-8") as fh:
            return json.load(fh)["stages"]
    except Exception:
        return []


def current_stage(state_text):
    """Return the stage number the project declares, or None. None means no enforcement."""
    match = STAGE_RE.search(state_text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def enforcement_mode(state_text):
    match = ENFORCE_RE.search(state_text or "")
    return match.group(1).lower() if match else "deny"


def open_decisions(state_text):
    """Pull the still-open decision headings out of the state file so they lead the session."""
    out = []
    for line in (state_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("###") and "UNDECIDED" in stripped.upper():
            out.append(re.sub(r"^#+\s*", "", stripped))
    return out


# --------------------------------------------------------------------------- context


def cmd_context():
    payload = stdin_payload()
    root = project_root(payload)
    state_path = find_state(root)

    parts = [read(os.path.join(LAYERS, "L0-contract.md")),
             read(os.path.join(LAYERS, "L1-router.md"))]

    if not state_path:
        parts.append(
            "## PROJECT STATE: none\n\n"
            "This project has no state file, so agent-os is not enforcing a stage here and the\n"
            "stage gate is off. If this is a build that will span more than one session, say so and\n"
            "offer to run `agent-os init` - one file is what stops the next session re-deciding what\n"
            "this one already decided.\n"
        )
    else:
        text = read(state_path)
        stage = current_stage(text)
        rel = os.path.relpath(state_path, root).replace("\\", "/")
        if stage is None:
            parts.append(
                "## PROJECT STATE: `%s`, no STAGE line\n\n"
                "The file exists but declares no stage, so the gate is off. Read the file, and if the\n"
                "project has a sequence, add a `STAGE: <n>` line to it.\n" % rel
            )
        else:
            stages = load_stages()
            meta = next((s for s in stages if s["id"] == stage), None)
            title = meta["name"] if meta else "unknown"
            head = "## PROJECT STATE: STAGE %d - %s   (source: `%s`)\n" % (stage, title, rel)
            body = read(os.path.join(LAYERS, "L2-stages", "stage-%d.md" % stage))
            if not body and meta:
                body = "%s\n\nGate: %s\n" % (meta.get("intent", ""), meta.get("gate", ""))
            opens = open_decisions(text)
            if opens:
                head += "\nStill undecided, and it leads this session:\n" + "\n".join(
                    "  - " + o for o in opens) + "\n"
            parts.append(head + "\n" + (body or ""))
            parts.append(
                "Stages before and after this one are deliberately NOT loaded. When the gate above is\n"
                "met, say so and ask the operator to confirm the advance; only then does the STAGE line\n"
                "change. Before this session ends, write what changed back into `%s`.\n" % rel
            )

    out = "\n\n---\n\n".join(p.strip() for p in parts if p and p.strip())
    if out:
        print(out)
    return 0


# --------------------------------------------------------------------------- gate


def matches(path, patterns):
    """Cheap glob: `src/**` -> prefix, `*.sql` -> suffix, anything else -> substring."""
    norm = path.replace("\\", "/").lstrip("./").lower()
    for pat in patterns:
        p = pat.replace("\\", "/").lower()
        if p.endswith("/**"):
            stem = p[:-3]
            if norm == stem or norm.startswith(stem + "/") or ("/" + stem + "/") in ("/" + norm):
                return pat
        elif p.startswith("*."):
            if norm.endswith(p[1:]):
                return pat
        elif p in norm:
            return pat
    return None


def edited_path(payload):
    ti = payload.get("tool_input") or {}
    for key in ("file_path", "notebook_path", "path"):
        if ti.get(key):
            return ti[key]
    return ""


def verdict(root, path):
    """Decide whether the current stage permits writing `path`.

    Returns (decision, reason) where decision is "allow", "warn" or "deny". This is the ONE place
    the rule lives; the Claude Code hook and the harness-agnostic `check` command both call it, so
    a project cannot be governed by two slightly different versions of the same gate.
    """
    state_path = find_state(root)
    if not state_path:
        return "allow", ""

    text = read(state_path)
    stage = current_stage(text)
    if stage is None:
        return "allow", ""

    mode = enforcement_mode(text)
    if mode == "off":
        return "allow", ""

    meta = next((s for s in load_stages() if s["id"] == stage), None)
    if not meta or not meta.get("deny") or not path:
        return "allow", ""

    # Only judge paths inside the project; never police files elsewhere on the machine.
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        return "allow", ""
    if rel.startswith(".."):
        return "allow", ""

    if matches(rel, meta.get("allow", [])):
        return "allow", ""
    hit = matches(rel, meta["deny"])
    if not hit:
        return "allow", ""

    reason = (
        "agent-os: STAGE %d (%s) does not allow writing `%s` (matched `%s`).\n\n%s\n\n"
        "This is a sequencing gate, not a permission problem. Either do the part that fits this "
        "stage, or tell the operator the gate is met and ask them to advance the STAGE line in %s."
        % (stage, meta["name"], rel.replace("\\", "/"), hit, meta.get("why", ""),
           os.path.relpath(state_path, root).replace("\\", "/"))
    )
    return ("warn" if mode == "warn" else "deny"), reason


def cmd_gate():
    """PreToolUse hook (Claude Code). Emits that harness's JSON decision shape."""
    payload = stdin_payload()
    root = project_root(payload)
    decision, reason = verdict(root, edited_path(payload))
    if decision == "allow":
        return 0
    if decision == "warn":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": reason}}))
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))
    return 0


def cmd_check(argv):
    """Harness-agnostic gate: `agent_os.py check <path>...`. Exit 1 if any path is denied.

    This is the enforcement path for anything that is not Claude Code - a git pre-commit hook, a CI
    step, a Makefile target, or an agent told to run it before writing.
    """
    if not argv:
        print("usage: agent_os.py check <path> [path...]")
        return 0
    root = os.getcwd()
    failed = False
    for path in argv:
        decision, reason = verdict(root, os.path.abspath(path))
        if decision == "deny":
            failed = True
            sys.stderr.write(reason + "\n")
        elif decision == "warn":
            sys.stderr.write("[warn] " + reason + "\n")
        else:
            print("allow: %s" % path)
    return 1 if failed else 0


# --------------------------------------------------------------------------- settle


ADVANCE_RE = re.compile(
    r"\b(gate (is )?(met|passed|clear)|stage (is )?(complete|done|passed)|"
    r"mov(e|ing) (on )?to stage|advanc\w* (to|past) stage)\b", re.I)


def cmd_settle():
    """Stop hook. If the reply claims a stage boundary was crossed, the state file must show it."""
    payload = stdin_payload()
    root = project_root(payload)
    state_path = find_state(root)
    if not state_path:
        return 0
    if payload.get("stop_hook_active"):
        return 0

    transcript = payload.get("transcript_path") or ""
    text = ""
    if transcript and os.path.isfile(transcript):
        try:
            with open(transcript, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()[-40:]
            for line in lines:
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                if msg.get("type") != "assistant":
                    continue
                for block in (msg.get("message", {}) or {}).get("content", []) or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text += block.get("text", "") + "\n"
        except Exception:
            return 0
    if not text or not ADVANCE_RE.search(text):
        return 0

    import time
    try:
        stale = (time.time() - os.path.getmtime(state_path)) > 900
    except OSError:
        return 0
    if not stale:
        return 0

    rel = os.path.relpath(state_path, root).replace("\\", "/")
    sys.stderr.write(
        "[agent-os] You said a stage gate was met, but %s has not been written this session. "
        "A decision that lives only in the transcript does not survive it. Record what closed the "
        "gate in that file (or say plainly that the gate is NOT met yet), then finish.\n" % rel)
    return 2


# --------------------------------------------------------------------------- init / stage


TEMPLATE = """# PROJECT STATE

> agent-os reads this file at session start and loads only the current stage's contract.
> Append to the log, never rewrite it. Only the operator advances the STAGE line.

STAGE: 0
enforcement: deny

## OPEN DECISIONS

### D1. <the question nobody has answered> UNDECIDED

*Settled: (not yet)*

## SETTLED DECISIONS

| # | decision | date | why |
|---|---|---|---|

## LOG - newest at the bottom, append only

"""


def cmd_init():
    root = os.getcwd()
    target = os.path.join(root, "PROJECT-STATE.md")
    if os.path.exists(target):
        print("already exists: %s" % target)
        return 0
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(TEMPLATE)
    print("wrote %s (STAGE 0, enforcement deny)" % target)
    return 0


def cmd_stage(argv):
    root = os.getcwd()
    state_path = find_state(root)
    if not state_path:
        print("no state file found under %s" % root)
        return 0
    text = read(state_path)
    if not argv:
        stage = current_stage(text)
        meta = next((s for s in load_stages() if s["id"] == stage), None)
        print("STAGE %s - %s   (%s)" % (
            stage, meta["name"] if meta else "no STAGE line", state_path))
        return 0
    try:
        new = int(argv[0])
    except ValueError:
        print("stage takes a number")
        return 1
    if not STAGE_RE.search(text):
        print("no STAGE line in %s - add one first" % state_path)
        return 1
    updated = STAGE_RE.sub("STAGE: %d" % new, text, count=1)
    with open(state_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(updated)
    print("STAGE -> %d in %s" % (new, state_path))
    return 0


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 0
    cmd = argv[0]
    try:
        if cmd == "context":
            return cmd_context()
        if cmd == "gate":
            return cmd_gate()
        if cmd == "settle":
            return cmd_settle()
        if cmd == "init":
            return cmd_init()
        if cmd == "stage":
            return cmd_stage(argv[1:])
        if cmd == "check":
            return cmd_check(argv[1:])
    except Exception:
        return 0  # fail open, always
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
