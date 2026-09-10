---
name: code-index
description: Generates a deterministic, greppable fact table — one line per fact — answering what you must know about a source file without opening it: what it is, its CLI, its internal imports, who breaks if you change an export, who runs it as a subprocess, who checks it, what it exports, and a file:line pointer to a load-bearing invariant. Use when asked who calls or depends on a file, what the blast radius of a change is, what a file does without reading it, or to set up or refresh a code index. Config-driven, derived never authored, and verified in CI with --check so it cannot drift. Saving is modest and measured — 1-3.4k tokens per fix, n=1, with a confound.
license: MIT
metadata:
  version: "0.4.0"
  author: token-audit contributors
---

# Code Index — a fact table you can trust without checking

One line per fact, answering *"what must I know about this file without opening it?"*

```
scripts/audit.mjs	IS	where did this session's tokens actually go?
scripts/audit.mjs	CLI	--file --json --list --no-paths --per-commit --project
scripts/audit.mjs	DEFINES	KINDS analyze classify encodeProject listTranscripts
scripts/audit.mjs	IMPORTEDBY	scripts/test/run-tests.mjs
scripts/audit.mjs	GUARD	scripts/test/run-tests.mjs
scripts/audit.mjs	WHY	scripts/audit.mjs:30 NO TOOL-RESULT CONTENT
```

| kind | answers |
|---|---|
| `IS` | what the file is, from its own header |
| `CLI` | its command surface, from the argv dispatch |
| `USES` | what it imports inside the repo |
| `IMPORTEDBY` | blast radius, compile-time — who breaks if you change an export |
| `SPAWNEDBY` | blast radius, runtime — who runs it as a subprocess |
| `GUARD` | who checks it |
| `DEFINES` | exported names |
| `WHY` | `file:line` of a load-bearing invariant in its own comments |

## Say what it is worth, and do not oversell it

**Measured saving in its home repo was 1–3.4k tokens per fix, n=1, with a real confound:**
the code was already in context for most of those fixes, so some of that saving is not
attributable to the index. **It is not the headline of this project — `token-audit` is.**
Say so if the user asks whether it is worth adopting. It is a modest, reliable saving on one
shape of question — *"who breaks if I change this"* — otherwise answered by reading four
files.

## Running it

```bash
node ${CLAUDE_PLUGIN_ROOT}/scripts/code-index.mjs --root <repo>            # write it
node ${CLAUDE_PLUGIN_ROOT}/scripts/code-index.mjs --root <repo> --check    # CI: fail if stale
node ${CLAUDE_PLUGIN_ROOT}/scripts/code-index.mjs --root <repo> --stdout   # print, write nothing
```

**Wire `--check` into CI in the same change that adds the index.** Derived-but-unverified is
strictly worse than nothing: the file drifts, and a stale fact table is a confident liar that
people stop double-checking precisely because it has been right before.

## Two properties, or it costs more than it saves

1. **Deterministic.** Sorted lists, nothing from the clock, nothing from filesystem order,
   **no generation date.** It is meant to sit in a cached prompt prefix — one volatile byte at
   the top invalidates every token after it and turns the saving into a cost. If you are asked
   to add a timestamp or a file count to the header, **refuse and explain this.**
2. **Derived, never authored.** Nobody edits it. If a fact is wrong, the generator or the
   config is wrong.

## Config is where the value is

Roughly **10% of a generator like this binds to a repo's house conventions** — the header
format, the argv dispatch shape, where the guard register lives, how the codebase writes
emphasis in comments — and that 10% is where all the value is. `code-index.config.json` at the
repo root holds it; this plugin ships its own as the worked example, with every field
commented.

**When adopting it in a new repo, read the config first and fit it to that repo's conventions
before generating anything.** A default-config run produces a plausible table full of near
misses, which is the worst possible first impression for a tool whose value is trust.

## What it deliberately gets wrong in the safe direction

`SPAWNEDBY` **under-reports**. A spawn target is recorded only when a whitespace-free string
literal reaches a spawn call directly or through one variable, and the target has a shebang. A
path that reaches a spawn through a loop variable is not found. This is on purpose: a missing
edge costs one grep, a wrong edge costs the trust that makes the table worth reading at all.
Tell the user this rather than presenting the graph as complete.

## If you change the generator

Every fact kind has a test naming the defect it exists for. **Assert against a fresh
`build()`, never against the committed artifact** — a mutated generator never rewrites the
file, so a suite that reads `CODE-INDEX.txt` stays green through any semantic breakage and
only the staleness check fires. That trap made this tool's first test suite dead.
