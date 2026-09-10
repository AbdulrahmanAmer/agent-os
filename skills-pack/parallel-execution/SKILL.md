---
name: parallel-execution
description: Fire when a written plan exists and you are working through it, or when several pieces of work are independent and none blocks another. Do NOT fire when there is no plan file - write one first, or just do the single slice - and do NOT fire when the pieces share files or state, or one needs another's output, because that is sequential work with extra coordination cost. Covers working a plan, delegating to subagents, and running independent work in parallel.
---

# Executing plans, and doing it in parallel when it pays

Three related motions. Which one applies depends on whether a plan exists and whether the work is
actually independent.

## Working a written plan: `references/executing-plans.md`

A plan file exists and you are implementing it. Follow its order. If a step turns out to be wrong,
change the plan and say so - do not quietly build something else and leave the plan describing a
system that no longer exists.

Verify each slice as it lands, not all of them at the end. A batch of unverified slices is one large
unverified change with extra steps.

## Delegating a slice: `references/subagent-driven-development.md`

A subagent starts with an EMPTY context. It inherits none of the thinking that produced its task,
which is exactly how a delegated slice comes back beautiful and wrong.

Every dispatch carries: the decisions its work depends on, pasted in rather than linked; ONE slice
with a stated exit condition; the rules that apply to it; the tokens or plan section it must build
against, quoted; and what it must not touch.

When it reports back, verify the claim yourself. A subagent's "done" is a claim, not proof. Never
use a subagent to review its own work, or yours.

## Running several at once: `references/dispatching-parallel-agents.md`

Only when the pieces are truly independent: no shared files, no shared state, and none of them
needs another's output. Test that before you fan out - two agents editing the same file
produce a merge nobody can resolve and work nobody can attribute.

When they are independent, dispatch them in ONE message so they actually run concurrently rather
than in sequence.

## The cost, stated plainly

A subagent is the most expensive call available: it re-establishes context from zero, reports back,
and then you read the report. If you could finish the work in a handful of tool calls yourself, do
that instead. Delegate for breadth, never for depth.
