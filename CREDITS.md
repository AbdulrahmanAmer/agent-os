# Credits

agent-os itself - `plugin/layers`, `plugin/scripts`, `plugin/hooks`, `build-bundle.py`,
`tools/` - is MIT, see [LICENSE](LICENSE).

The `skills-pack/` directory is a curated set of skills that the router in `L1-router.md` points
at. They are bundled so the system is standalone: a router naming capabilities the project does
not have is a router pointing at nothing. Their origins differ, and this file records that rather
than quietly implying one author.

## Written for this toolchain

- **design-tournament** - the section-by-section, multi-persona design protocol. Built and proven
  on a real client site across two runs.
- **design-from-references** - the derive-a-written-token-system-before-any-component method, taken
  from what produced the OmniSuite dashboard demo.
- **dna-website** - full-site capture to a local inspectable directory.
- **codebase-index** - three retrieval tiers (`code-map`, `code-index`, and a structural graph)
  behind one entry point. The `code-map` and `code-index` components declare MIT.
- **quiet-tests** - MIT.

## From upstream skill packs

Merged or bundled largely as published, with descriptions rewritten as triggers and, in four
cases, several related skills combined behind a single entry point:

- **Superpowers** (obra) - `brainstorming`, `writing-plans`, `test-driven-development`,
  `systematic-debugging`, `verification-before-completion`, `using-git-worktrees`,
  `finishing-a-development-branch`, plus `code-review` (merged from `requesting-code-review` and
  `receiving-code-review`) and `parallel-execution` (merged from `executing-plans`,
  `subagent-driven-development` and `dispatching-parallel-agents`). Each original SKILL.md is
  preserved verbatim under the merged skill's `references/`.
- **Framer Motion** (official skills) - `motion`, merged from the core, scroll and variants skills.
- **scroll-craft** (nateherk-design) - the scroll-driven landing page builder.

If you own one of these and want it removed from this bundle, open an issue and it goes.

## Deliberately not included

Three things are stripped from `dna-website` before it is published, and none of them are code:

- `.dna-website.env` - a live login email and password.
- `real-projects/` - captures of a private business site.
- `node_modules/` - 26 MB that its own `package.json` reinstalls.
