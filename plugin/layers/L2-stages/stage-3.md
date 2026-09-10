### What this stage is for

Working the plan in order. One slice at a time, each ending in something that renders and is
verified when it lands.

### How to behave

Follow the plan's order; if a slice turns out to be wrong, change the plan and say so - do not
quietly build something else. Index the codebase before you go hunting for symbols, and re-index
after a structural change, because a stale map is worse than no map.

Verify each slice as it lands, not all of them at the end. A batch of unverified slices is one
large unverified change with extra steps.

Delegated work gets the current stage, the decisions it depends on pasted in, one slice, and a
stated exit condition. An agent starting from an empty context will otherwise build something
beautiful and wrong.

### Gate

Every slice in the plan closed and verified.
