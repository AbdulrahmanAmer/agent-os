---
name: design-from-references
description: "Fire when reference images have been supplied and a real interface is wanted, or when a build looks generic and you need to find out why. Do NOT fire when a token system already exists for this project - consume it rather than deriving a second one - and do NOT fire when there is no reference material at all, because the fix for that is to go and get some, not to invent a layout."
---

# Design from references

The method that produced the OmniSuite dashboard demo (live at https://omnisuite-demo.pages.dev).
It is written down because of what that project recorded in its own token file:

> *"Derived from seven dashboard references supplied by the owner. Writing the system down because
> the first attempt ignored all of it and produced a generic dark template."*

That sentence is the whole reason this skill exists. The first pass had the references and still
produced a memorised layout. What fixed it was not more taste - it was **writing the system down
before writing components**, so nothing downstream could quietly fall back.

## The method

**1. Read the images. Actually read them.**
Open every reference with the Read tool. They are evidence, not decoration. Write down, per image:
surface hierarchy, how panels separate from the page, where emphasis lives, what the accent is
used for, type roles, density. If a detail is visible only in an image and not in any text you
were given, say so explicitly - that is exactly where the value is.

**2. Write the system down BEFORE any component.**
Produce a token file whose header states the rules in prose, then the tokens. Not a palette dump -
RULES, in the imperative, each one falsifiable. The proven shape is four:

- **Surface hierarchy.** e.g. `ground -> card -> hero`. Say how levels separate (fill contrast and
  a soft shadow, never a 1px outline) and how many of the top level may exist per view (exactly
  one). A hierarchy without a count is not a rule.
- **Layout grammar.** e.g. bento, not grid: cards differ in size and span, small cards nest in big.
- **Restraint.** e.g. monochrome plus almost nothing.
- **The accent, ENUMERATED.** Never "use sparingly" - that is unenforceable and it drifted to
  eleven places in the reference project before it was listed. Write the closed list: the primary
  button, the assistant's own presence, the current position in a deliberate sequence. Anything
  else uses ink or a status colour. Status colours are reserved and never double as the accent.

**3. Make the theme contract explicit.**
`:root` is one complete palette; `:root[data-theme="dark"]` overrides TOKENS ONLY. No component may
declare a colour inside a theme block - if a value differs between themes it becomes a token, or
dark mode silently breaks. Anything drawn on a surface that INVERTS (a hero card that goes light-on-
dark while the page stays light) needs its own `--on-*` token.

**4. Check contrast, do not vibe it.**
Annotate the ratio next to any token used for text (`--ink-2: #6B6862; /* body copy. ~5.6:1 on
white */`). Call out the traps in the file itself: an accent that is 1.9:1 on white is a FILL behind
near-black ink, never text.

**5. Components consume tokens only.**
A literal hex inside a component is a defect, not a shortcut. If you find yourself typing one, the
system is missing a token - go add it with its rule.

**6. Build one screen, then look at it.**
Render it and read the screenshot before building the other nine. A demo that was never looked at
is unverified, whatever the build says.

## Worked example

`examples/omnisuite-tokens.css` is the real token file from that demo - 213 lines, the four rules
in the header, then surfaces, ink, the enumerated accent, reserved status colours, and the theming
contract. Read it before writing your own; copy its STRUCTURE, never its values.

The demo it produced: 10 screens, ~1,550 lines of TSX, one fixtures file, and a 228-line
walkthrough script written for a live meeting. Static, no backend, deployed on Cloudflare Pages.

## The failure this skill exists to stop

You have seen a few dozen dashboard and landing layouts in training. Under time pressure you will
reach for one, and it will look competent and generic - a centred hero, three cards, a table, a
footer. The reference images are the only thing standing between the operator and that output. If
you cannot point at the reference (or the written rule derived from it) behind a design decision,
you are pattern-matching, not designing. Stop and go back to step 1.
