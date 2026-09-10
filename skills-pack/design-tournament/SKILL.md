---
name: design-tournament
description: "Fire when a whole surface has to be lifted to agency tier, or when a previous polish pass was called too subtle. Do NOT fire for one component or a spacing tweak, and do NOT fire once the direction has been chosen and written down as tokens, because then you are executing a direction rather than competing directions."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Workflow
---

# Design Tournament — the protocol

A reusable, niche-adaptive methodology for turning a template-feeling page into something that
reads as genuinely agency-built. Built and proven on a real client site (Eli Buys Homes, a cash-
home-buyer business) across two runs: a first pass that upgraded the shared design system and
enriched content (real but judged "still too subtle"), and a second pass — this protocol — that
ran a full section-by-section personality tournament and closed the gap. Read this whole file
before running the protocol again; it encodes real lessons from real failures, not just the happy
path.

## When a lighter pass is enough vs. when to run the full tournament

Not every upgrade request needs this. Use the lighter, single-agent "craft-doc-grounded upgrade"
pattern (read the relevant Open Design craft docs, ground fixes in real facts, apply directly,
verify with Playwright) when the ask is a normal polish/fix pass. Reach for the full tournament in
this file when the user explicitly asks for exhaustive/agency-tier/"upgrade everything" work, or
when a lighter pass already ran and was judged genuinely too subtle by an honest critique — that's
the real signal this protocol exists to answer, not a default for every request.

## The core idea

A single agent (or even three agents each doing a full independent page) tends to converge on
similar, safe, "good enough" output. Real variety requires structural competition: multiple
distinct design personalities, each genuinely grounded in a different real reference, independently
attacking the SAME section, followed by an honest synthesis step that grafts the strongest ideas
from each rather than picking one winner. This is the Workflow tool's "judge panel" pattern applied
to visual design instead of text.

---

## Phase 0 — Niche and vibe intake (do this before selecting anything)

Before picking references, know what you're actually designing for. Read (or ask for, if it
doesn't exist yet):
- The client's real brand facts and knowledge bank (never invent facts — if something like a
  founder identity, a trust number, or a specific claim is unconfirmed, treat it as off-limits,
  not as license to invent one).
- The existing site's real current tokens (colors, fonts, spacing) — a tournament should push
  craft and structure hard, but a REAL client's brand identity (their actual logo, their actual
  established color) is not something to swap out; work within it, the same way this protocol's
  first Eli Buys Homes run kept the real gold/ink/paper/blue-link tokens and only expanded
  technique around them.
- The real niche: what kind of business, what emotional register does a visitor need (trust?
  warmth? urgency? technical credibility?), who is the actual audience.

## Phase 1 — Reference selection (the "fetch from the Open Design brain" step)

**External dependency, and this skill is degraded without it.** The reference library ships with the
Open Design desktop app, which is a separate install. Its location varies by machine and OS - on
Windows it is typically `%LOCALAPPDATA%\Programs\Open Design\resources\open-design\`. If that
directory does not exist, say so and fall back to references the operator supplies; do NOT grade a
variant against a library you cannot read and report the score as if you had.

The library contains:
- `design-systems\<name>\DESIGN.md` — 150+ real, mined brand design systems (Notion, Linear, Cal.com,
  Stripe-adjacent, Coinbase, Airbnb, editorial, luxury, brutalism, and many more — `Glob
  design-systems\**\DESIGN.md` to see the current full list, it grows).
- `craft\*.md` — universal, niche-agnostic craft law: `anti-ai-slop.md`, `color.md`,
  `typography.md`, `typography-hierarchy.md`, `typography-hierarchy-editorial.md`,
  `animation-discipline.md`, `laws-of-ux.md`, `state-coverage.md`, `accessibility-baseline.md`,
  `form-validation.md`, `rtl-and-bidi.md`. These apply to every niche, every persona, always.

**Selection heuristic (adapt per niche, this is guidance not a fixed table):**

| Niche register | Good reference candidates | Why |
|---|---|---|
| Financial trust / high-stakes decision (cash offers, fintech, insurance, legal) | coinbase, mastercard, mongodb (technical trust) | Bold-but-serious hierarchy, numbers/proof leading, zero decorative noise |
| Warm local service / hospitality / community | notion, airbnb, cafe | Warm neutrals, approachable restraint, human-scale typography |
| Technical / developer / SaaS-precision | linear-app, cal, framer | Ultra-minimal precision, confident dark-or-light restraint, signature type weights |
| Narrative / story-driven / editorial / documentary | editorial, luxury | Asymmetric layouts, pull-quotes, typographic richness, photo-essay pacing |
| Playful / consumer / low-stakes fun | duolingo, pinterest, colorful | Bold color use, motion-forward, higher energy tolerance |

Pick 2-4 references per project (not per section) that genuinely fit the real niche/vibe from
Phase 0 — these anchor the personas in Phase 2. Do not default to the same references every time;
re-run this selection step for every new niche. If unsure, read 3-4 candidate DESIGN.md files in
full before committing (they're a few hundred lines each, cheap to read, expensive to guess wrong).

## Phase 2 — Persona definition

Construct 3 named personas (3 is proven; more increases cost without proportionate variety gain
past that). Each persona needs:
- A real name and a one-paragraph point of view / voice (not just "designer A/B/C" — genuine
  personality produces genuinely different output; see the worked example below).
- One anchoring Open Design reference (from Phase 1) they're instructed to actually read before
  designing, plus the full craft-doc pack (Phase 1's `craft/*.md` set) which every persona shares
  regardless of individual style, since those are universal law, not style.
- Explicit instruction that they're in competition — two other personas are attacking the same
  section right now with different sensibilities, so make the output unmistakably theirs.

**Worked example (Eli Buys Homes, cash-home-buyer, San Ramon CA):**
- *Vera — The Minimalist* (notion + cal): restraint as confidence, whitespace as luxury.
- *Marcus — The Trust Architect* (coinbase): proof and numbers lead, adjectives follow, bold means unambiguous not loud.
- *Iris — The Documentarian* (editorial): treats real seller situations as a magazine feature, not a sales page.

## Phase 3 — Section inventory (do not leave chrome untouched)

Enumerate EVERY real section that needs coverage, not just the obvious "hero and features" content
blocks. **Real lesson from this protocol's first run:** header/nav, footer, and the final CTA band
were left out of the first tournament pass and the operator had to explicitly ask for them in a
follow-up — treat header, footer, and closing CTA as first-class tournament sections from the
start, not an afterthought. For each section, write a clear locate-hint (a distinctive class name
or heading text) so agents can find it in the real file without ambiguity.

## Phase 3.5 — Responsive and viewport coverage (non-negotiable, not a bolt-on pass)

**Real lesson from this protocol's second run:** the first two tournament runs verified 1440px
desktop only during the actual design stage (mobile was checked, if at all, as an afterthought in
assembly/final-gate) — meaning mobile layout was never actually *designed*, just whatever fell out
of desktop-first CSS. This produced a page that "looked perfect at first glance" and had zero real
mobile design. Treat this as a hard requirement baked into every phase from here on, not a
follow-up pass:

- **Every persona variant, every section, screenshots at a minimum of three viewports**: desktop
  (1440px), tablet (768px), and mobile (390px). A variant is not "done" until the designer has
  looked at all three, not just desktop.
- **The judge/synthesis stage synthesizes across all three simultaneously** — the winning version
  must genuinely work at every breakpoint, not just look good at 1440px with mobile as collateral.
  A layout idea that can't translate to a coherent mobile treatment loses to one that can, even if
  the desktop version is individually weaker.
- **Zoom and reflow, not just fixed breakpoints.** Real users zoom browsers in and pinch-zoom on
  mobile. Verify text reflows without horizontal scroll or clipped content at 200% browser zoom
  (WCAG 1.4.4/1.4.10) — avoid fixed pixel widths/heights on text containers, prefer relative
  units and `clamp()`/`min()`/`max()` for type scale so zoom and viewport both degrade gracefully
  instead of breaking.
- **Touch vs. hover, not the same interaction model.** Anything designed as a hover reveal (a
  hover-only tooltip, a hover-triggered card flip) needs a real touch-equivalent — tap-to-reveal,
  always-visible on mobile, or a redesigned interaction, not a feature that silently vanishes under
  320px. Tap targets minimum 24x24 CSS px (WCAG 2.5.8 AA floor).
- **The motion pass (Phase 6) must design touch interaction explicitly**, not just port hover
  effects — pointer-fine/hover-capable checks (`(hover: hover) and (pointer: fine)`) should gate any
  hover-only motion, with a real touch-appropriate substitute for touch devices, never a silent gap.
- **The final gate (Phase 7) verifies responsiveness with code, not eyeballing**: real Playwright
  checks at all three viewports for horizontal overflow (`document.documentElement.scrollWidth >
  document.documentElement.clientWidth`), tap-target sizing, and text reflow at 200% zoom — plus
  actual screenshots at each breakpoint, viewed, not assumed.

## Phase 4 — The tournament (pipeline over sections, parallel personas per section)

For each section, in a `pipeline()` (sections proceed independently, no barrier between them):
1. `parallel()` across personas: each persona agent reads the real page + real shared CSS + their
   assigned reference + the craft pack + real brand facts, then builds a COMPLETE remake of ONLY
   their assigned section in an **isolated scratch copy** of the real page (never edit the real
   file directly here — this is the exact mechanism that prevents concurrent-write corruption when
   multiple personas/sections run in parallel). Per Phase 3.5, they design and screenshot their
   remake at desktop/tablet/mobile in real page context (surrounded by the real header/adjacent
   sections, not an isolated floating fragment) via Playwright, actually look at all three
   screenshots, and report back the section HTML/CSS, all three screenshot paths, and their
   rationale — including how the layout adapts across breakpoints, not just how it looks at 1440px.
2. One judge/synthesis agent per section: reads all N variant reports, **actually views every
   screenshot at every viewport** (never judge from text descriptions alone, never judge desktop
   only), identifies concretely what's strongest in each — including which variant's *responsive*
   behavior is strongest, not just its desktop look — and synthesizes ONE combined version that
   grafts the best ideas together across all breakpoints. It builds its synthesis in its own
   scratch file, screenshots it at all three viewports, looks at all three critically, and does at
   least one refinement iteration (v1 -> critique -> v2) before finalizing.

## Phase 5 — Assembly (single-threaded, always)

**This is the single most important structural rule in this entire protocol.** Once every section
is finalized, ONE agent — never parallel agents — applies every finalized section to the real page
file and merges any new CSS into the real shared stylesheet, in one pass. Multiple sections'
worth of new CSS classes can conflict or duplicate; a single assembly pass reads the current real
state of the shared files, merges deliberately, deduplicates against what's already there, and
re-verifies the whole assembled result (screenshots, console errors, cardinal-sin re-check now
that everything is combined). Never let two agents write to the same shared CSS/HTML file
concurrently — this has caused real, confirmed corruption risk in every run of this protocol so far.

## Phase 6 — Motion pass (dedicated, after structure is locked)

Motion is its own pass, applied AFTER assembly, not fought over per-variant during the tournament
(variants may sketch motion intent in comments, but final timing/choreography is unified here so
the whole page feels like one system). Ground every number in `craft/animation-discipline.md`:
150ms default state-confirmation, 200-300ms entering UI, 300-500ms cross-element choreography,
never exceeding 500ms for a non-cross-screen transition. The real differentiator between
"template" and "agency" motion is **staggered multi-element entrance** (each child +40-80ms after
the previous, never everything firing at once) and **physical-feeling interaction** (spring-like
easing on transform/position, not linear). Every reveal must still start at `opacity:1` in its base
CSS rule — motion is progressive enhancement layered by JS-added classes, never a precondition for
content existing (a real regression this protocol guards against every run). Respect
`prefers-reduced-motion` throughout.

## Phase 7 — Independent adversarial final gate

One agent with **no stake in the work** (not the assembly agent, not a persona) reviews the whole
result the way a demanding client who's paid real agencies before would. It takes fresh screenshots
(never trust the tournament's own screenshots — always re-verify from a clean, independent pass),
checks for real bugs with code (broken-image scan, overflow scan, console errors — not just
eyeballing), cross-checks every anti-ai-slop cardinal sin one final time now that everything is
combined, and gives a direct, unsoftened verdict per section plus a punch list. If the punch list
has real issues, fix them (directly, or via one more scoped tournament pass) and re-verify — don't
report "done" on an unresolved punch list.

---

## Hard constraints (every persona, every phase, no exceptions)

- Never fabricate: no invented testimonials, names, review counts, stats, or metrics. Every claim
  traces to the real brand facts. If an identity or story detail is unconfirmed, it stays off-limits.
- Never touch/regenerate logo or other confirmed-real brand image assets — reference as-is.
- Relative paths only; every page stays a complete, valid, self-contained document matching the
  site's existing build convention (no build step, no framework, unless the target site already has one).
- No em-dashes in any written copy — hyphens only (this workspace's global copy-hygiene rule;
  drop this constraint only if the target project has no such rule).
- Respect `prefers-reduced-motion` and the no-JS-safe base-opacity rule for all motion, always.

## Known pitfalls (real bugs hit while building this protocol — do not repeat them)

1. **The double-wrapped template-literal bug.** When building a Workflow script that interpolates
   one agent's prior results into a later agent's prompt, write `${variants.map(...).join(...)}`
   directly inside the outer template literal. Writing `${'${variants...}'}` (wrapping the
   interpolation in an extra string literal) produces the LITERAL TEXT of the expression instead of
   evaluating it — the downstream agent receives dead template syntax instead of real data. This
   bug hit this exact protocol twice in one session. Before launching any multi-stage Workflow
   script that threads results between stages, grep the script for the literal pattern `${'${` —
   if it matches anything, it's this bug.
2. **Concurrent writes to a shared file.** Never let parallel agents (different personas, different
   sections) write to the same real CSS/HTML file. Always route through scratch copies during
   generation and a single-threaded assembly step at the end (Phase 5).
3. **Trusting a self-report over a screenshot.** Every stage that claims "renders correctly" must
   have actually looked at a real screenshot, not just reasoned about the HTML/CSS. This applies
   doubly to the judge/synthesis and final-gate stages, which exist specifically to catch what a
   single agent's self-report would miss.
4. **Leaving chrome out of the section inventory.** Header, footer, and the closing CTA are real
   sections a visitor sees on every page — include them in Phase 3 from the start.
5. **Designing desktop-only and checking mobile as an afterthought.** A page can look flawless at
   1440px and have no real mobile design at all if every tournament stage only screenshots one
   viewport. Responsiveness is not a QA checkbox at the end — see Phase 3.5, baked into every stage.

## How to invoke this protocol again

Build a `Workflow` script following Phases 4-7 literally (pipeline over sections -> parallel
personas -> judge/synthesis -> single-threaded assembly -> motion pass -> independent final gate).
Reuse the persona/reference-selection heuristic from Phase 1-2 for the new niche rather than
copying the Eli Buys Homes personas verbatim. Scope each run to ONE page at a time unless
explicitly told to run multiple pages in parallel (running multiple pages that share a CSS file
in true parallel reintroduces pitfall #2 at the page level, not just the section level).
