---
name: code-review
description: Fire when a change is finished and about to be accepted, merged, or reported done, and when review feedback has landed and you are deciding what to do with it. Do NOT fire when nothing changed, when the change is copy or a config value, or when you already agree with every point of the feedback - then just apply it. Covers both directions of review - asking for one on your own work, and receiving one without either caving or dismissing.
---

# Code review, both directions

Two situations, one skill, because they are the same discipline seen from either end: a claim about
code is only worth what the evidence behind it is worth.

## Asking for review on your own work

Read `references/requesting-code-review.md` when a change is finished and about to be accepted.

The short version: state what the change was supposed to do, show the evidence that it does it, and
name the parts you are least sure about. A review request that says "please review" gets a review of
whatever the reviewer happened to look at. A request that names the risky part gets a review of the
risky part.

You cannot review your own work in the same pass that wrote it. The context that produced the code
is the context that will agree with it.

## Receiving review feedback

Read `references/receiving-code-review.md` when feedback lands, especially when some of it looks
wrong.

The failure mode here is agreement as a reflex. A reviewer, human or model, is sometimes wrong about
this codebase, and applying a wrong fix politely is worse than arguing. For each point: verify the
claim against the actual code, then either apply it, or say why you are not applying it and what you
checked. Both answers are acceptable. Enthusiastic agreement followed by a patch nobody verified is
not.

Work all the findings as one design problem before you touch anything. Fixing them one at a time,
each in its own pass, is how a single finding turns into a chain of commits that each break
something new.
