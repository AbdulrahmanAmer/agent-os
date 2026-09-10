# agent-os

Most agent setups give a project a pile of rules and hope the model reads them. This gives a
project a **stage**, loads only that stage's context, and refuses the edits the stage forbids.

Costs ~0 always-on tokens: nothing is added to the system prompt. Context is injected at session
start, and only when a project actually declares a stage.

## Install

**Claude Code (plugin, one time, applies to every project):**

    claude plugin marketplace add AbdulrahmanAmer/agent-os
    claude plugin install agent-os@agent-os

**Any project, any harness (drop-in):** download `agent-os-core-<version>.zip` from
[Releases](../../releases), extract at the project root, then:

    python .agent-os/scripts/install.py

It detects the harness and wires the strongest adapter that harness supports, then tells you what
it did.

## What a project gets

A state file it owns - `.agent-os/STATE.md` or `PROJECT-STATE.md`:

    STAGE: 0
    enforcement: deny      # deny | warn | off

Create one with `python .agent-os/scripts/agent_os.py init`.

**No state file means nothing is enforced.** Not a default of stage 0 - nothing. Every hook fails
open: a missing file, no python, a malformed payload, an unparseable stage, all proceed silently. A
context tool that blocks a session is worse than no tool.

### The stages

| # | stage | ends when |
|---|---|---|
| 0 | SHAPE | every open decision is answered in writing |
| 1 | DESIGN DIRECTION | a winner picked from rendered options, written down as tokens |
| 2 | SYSTEM DESIGN | the plan exists, is read, and is sliced with verifiable exits |
| 3 | BUILD | every slice closed and verified as it landed |
| 4 | HARDEN | the demo-ware list is clean and there is a rollback path |
| 5 | LAUNCH AND ITERATE | verified live, watched, next slice chosen deliberately |

Stages 0 to 2 refuse writes to `src/`, migrations and framework config. Stages 3 to 5 refuse
nothing, because by then sequencing is the plan's job, not the gate's. The rules are data, in
`plugin/layers/stages.json` - edit them for a project whose sequence differs.

## What is portable and what is not

The content (`layers/`) and the CLI (`scripts/agent_os.py`, dependency-free python) run under any
harness, or none. Enforcement is different, because a gate needs the harness to ask permission
before it writes:

| harness | what you get |
|---|---|
| **Claude Code** | REAL. Hooks deny a stage-forbidden edit before it happens, inject the stage context at session start, and block a stage-advance claim the state file never recorded. |
| **Codex CLI** | ADVISORY. Context renders into `AGENTS.md`, which Codex reads. No pre-write hook exists, so the stage instructs rather than stops. |
| **opencode** | ADVISORY, same mechanism. |
| **git** | REAL, and harness-independent. A pre-commit hook runs the gate over staged files and refuses the commit. |

Pair the git backstop with an advisory harness and you get enforcement even when the agent ignores
its instructions:

    python .agent-os/scripts/install.py --harness codex git

## Layers

Loosely after ICM (*Folder Structure as Agent Architecture*), which argues context should be laid
out as a filesystem where each stage loads only its own layer:

    layers/L0-contract.md    the operating contract - always injected
    layers/L1-router.md      which capability fires, and when it must NOT
    layers/L2-stages/*.md    one per stage - ONLY the current one is loaded
    layers/stages.json       the gate rules, as data
    layers/L3-reference/     durable reference

Loading every stage's instructions at once is the anti-pattern: material for stage 5 is noise
during stage 0, and that noise is what makes a session drift into work nobody asked for.

Honest about what this buys: determinism and fewer wasted tokens, not correctness. It stops a
session re-deciding what a previous session already settled. It does not make the model smarter.

## Commands

    agent_os.py context            print the current stage's context (any harness, no hooks)
    agent_os.py check <path>...    the gate as a command - exit 1 if the stage forbids a path
    agent_os.py stage              what stage is this project in
    agent_os.py stage 1            advance it
    agent_os.py init               write a state file

After a stage change, re-render the advisory blocks: `install.py --refresh`.

## Building

    python build-bundle.py --core     # dist/agent-os-core-<v>.zip
    python tools/scan-bundle.py dist/*.zip

The scanner fails a bundle that carries a path from the build machine or a `.sh` without its unix
executable bit. Both were real defects: zipfile records the source mode, and on Windows that is
0o666, so hooks extracted on macOS or Linux arrived unrunnable - a bundle that worked perfectly on
the machine that built it and silently did nothing anywhere else.

## Licence

MIT. See [LICENSE](LICENSE).
