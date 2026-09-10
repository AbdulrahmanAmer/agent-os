---
name: codebase-index
description: Fire when you need to locate a symbol, find who calls something, or know what breaks if you change an export - before opening files to hunt for it. Do NOT fire for prose, config values, copy, or any text search, where grep is the correct tool, and do NOT fire on a codebase small enough to hold in your head. Three tiers behind one entry point - a symbol cache for "where is it", a fact table for "what breaks", and a structural graph for call chains.
---

# Finding things without re-reading files

The expensive habit in a long session is not searching, it is RE-READING: opening the same file for
the third time to find one function. These three tools each answer a different question, and they
are ordered by cost.

Use them in this order. Stop at the first one that answers the question.

## 1. Where is it? Use `code-map`

About 50 tokens instead of opening the file. It keeps a verified per-repo symbol cache: where a
function, class, route, table or heading lives. Every answer is re-checked against the file on disk,
so a stale entry produces a MISS, never a wrong location.

Regex based and deliberately incomplete. On a miss, fall back to Grep - that is the designed
behaviour, not a failure. Setup and detail: `references/code-map.md`.

## 2. What breaks if I change it? Use `code-index`

A deterministic, greppable fact table: one line per fact per file. What the file is, its imports,
who breaks if you change an export, what it exports, and a pointer to the invariant that matters.

Config-driven and derived, never hand-written, with `--check` in CI so it cannot drift. The ~10% of
config that binds it to a codebase's conventions is where its value comes from - set that up early
rather than accepting the defaults. Detail: `references/code-index.md`.

## 3. What is the call chain? Use the structural graph

`codebase-memory` runs over a knowledge graph: inbound and outbound call paths, dead code, fan-out,
cross-service impact. Roughly 500 tokens for a structural question that costs tens of thousands via
grep-and-read and still misses callers.

Index the repository on the first session that has code, and RE-INDEX after any structural change:
new files, moved modules, renamed exports. A stale map is worse than no map, because you will trust
it. Query reference: `references/codebase-memory.md`.

## The honest caveat

On a small, flat, early-stage codebase all three buy less than plain read-discipline does. The real
cost early is whole-file re-reads, not searches. Read slices, keep what you already loaded, and do
not build an index for twelve files.
