---
name: motion
description: Fire when building animation in React with Framer Motion - a component that animates, a scroll-linked effect, or a choreographed sequence of several elements. Do NOT fire for a CSS transition or a hover state, which need no library, and do NOT fire before the layout is settled, because animating a composition you are still changing is wasted work. Three references behind one entry point - core API, scroll linkage, and orchestration.
---

# Motion in React

Animation is the last thing you add, not the first. If the layout is still moving, the motion work
gets thrown away with it. Settle the composition, then animate it.

Pick the reference by what you are actually building.

## Core API: `references/framer-motion-core.md`

`motion` components, `useMotionValue`, `useTransform`, `useSpring`, `useAnimationState`. The base
layer: one element, animated, with values you can drive.

Start here when the question is "how do I animate this element".

## Scroll-linked: `references/framer-motion-scroll.md`

`useScroll`, scroll-driven transforms, parallax, progress indicators. Anything where the scroll
position IS the timeline.

Start here when the effect is tied to how far down the page the visitor is.

## Orchestration: `references/framer-motion-variants.md`

Variants as state machines, `stagger`, sequencing, repeat, choreography across several elements.

Start here when more than one thing moves and the relationship between them is the point.

## Two rules that apply to all three

**Honour `prefers-reduced-motion`.** Not as a courtesy - motion sickness is real, and a site that
ignores the setting is broken for those users. Every moving thing needs its reduced variant.

**Verify by looking.** An animation that compiles tells you nothing. Watch it at desktop width, at
mobile width, and with reduced motion on. An animation loop that never settles is invisible to a
build and obvious in a browser.
