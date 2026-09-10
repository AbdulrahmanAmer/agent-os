# FAQ

> Design-decision rationale. If you're wondering "why doesn't it do X?", the answer is probably here.

---

## What this tool is

### What does this actually produce?

A directory of:
- The raw captured HTML, CSS, screenshots, and assets for every page (sanitized of credentials).
- A derived design system: color palette, type scale, spacing, radii, shadows, motion, breakpoints.
- A content inventory: every heading, paragraph, CTA, image, alt text.
- A component pattern catalog: repeated UI structures with examples.
- A rebrand layer: token templates with placeholders + a swap map from original to placeholder.
- A local browser inspector you can navigate offline.

You inspect, study, and rebuild from this output. You don't deploy it.

### Why isn't the output directly deployable?

Three reasons:
1. **Legal.** The captured HTML, CSS, images, and especially fonts are copyrighted material. Republishing them without rights is infringement.
2. **Technical.** Captured pages include site-specific JavaScript, vendor prefixes, inline analytics, and tags coupled to the original infrastructure. Stitching this into your stack would take longer than rebuilding.
3. **Editorial.** The interesting output is the *design system*, not the *HTML strings*. The rebrand layer gives you that, in a clean form you can apply to your own components.

If you want a one-click site cloner, this isn't it — and tools that do that uncritically tend to land their users in legal trouble.

### Why not just use HTTrack / wget / curl?

Those tools dump bytes. This tool also:
- Renders pages (so SPA content actually shows up)
- Extracts computed styles, not just declared CSS
- Derives a design system
- Handles authentication
- Produces structured analysis rather than a directory of unmodified HTML

If you only need static HTML, use wget. If you need design DNA, use this.

### Why is the inspector a separate Node server, not just static HTML?

Three reasons:
1. **Asset path rewriting at request time** — the inspector serves on-the-fly rewrites of asset URLs so the same captured HTML works regardless of where the output directory lives on disk.
2. **Live token swap preview** — future feature: edit `rebrand/tokens.css` and see the rendered page update.
3. **Optional cross-page diff overlays** — future: highlight changes across runs.

Static file serving via `python -m http.server` works for casual inspection but skips the rewrites.

---

## Why these algorithmic choices

### Why LAB color space for clustering?

RGB distance doesn't match perceived color distance. Two #88AAFF blues that look identical to a human can be far apart in RGB; two reds that look obviously different can be close. LAB (CIELAB) is designed for perceptual uniformity — euclidean distance in LAB ≈ delta-E ≈ perceived color difference.

This matters because:
- Without LAB, clustering merges colors that look different and splits colors that look the same.
- The output palette is for *humans* — designers and developers. It needs to match what their eyes see.

Cost: small (one transform per pixel, cached).

### Why multiple k values and silhouette selection, instead of a fixed k?

Real sites have wildly varying palette complexity:
- A minimalist marketing site: 4 colors.
- An e-commerce site with category badges, status indicators, sale colors: 30+ colors.

Fixed k under-clusters complex sites or over-clusters simple ones. Silhouette score across `K_CANDIDATES = [6, 8, 12, 16, 20]` lets the algorithm pick the k that best fits the actual color distribution.

### Why GCD for spacing detection?

Design systems are built on a base unit, multiplied. 4 / 8 / 12 / 16 / 24 / 32 → base of 4. 8 / 16 / 24 / 32 → base of 8. The greatest common divisor of all spacing values is the base unit by definition.

Outliers (one 7px padding from a one-off button) would corrupt the GCD. So we filter for values that appear `SPACING_MIN_OCCURRENCE` times (default 3) before computing GCD.

### Why component pattern detection by structural signature?

A "card" isn't a CSS class — it's a structural pattern. Different sites name their cards differently (`.card`, `.tile`, `[data-component=Card]`, no class at all). Class-name matching would miss most of them.

Instead, we hash the DOM subtree's structure (tag names + attribute existence, ignoring values, recurse to depth `COMPONENT_RECURSION_DEPTH`). Same structure → same hash → same pattern. Three matching structures → "this is a repeated component."

Limitations:
- Two visually-different components with same structure (e.g. card and testimonial) won't be distinguished. We rely on role-guessing heuristics (presence of img, heading, blockquote) to assign meaningful names.
- A pattern that only appears once isn't detected (`COMPONENT_MIN_OCCURRENCE = 3`).

---

## Why these implementation choices

### Why Python for the orchestrator, not Node?

- Ecosystem for image/color/numerical work (scikit-learn, numpy, Pillow, colorthief) is mature in Python.
- Pydantic for data contracts beats anything in the Node world for ergonomics.
- Playwright has equivalent quality in both — but most users have Python tooling already.
- Inspector is Node because that's where Express + css-tree live.

### Why a Pydantic model for every JSON file, not just `dict`?

Three reasons:
1. **Refactor safety.** When the schema changes, models flag mismatches at load time, not three stages later when a downstream consumer hits a missing field.
2. **Documentation.** The models *are* the schema. New contributors read `models.py` to understand the data flow.
3. **Schema versioning.** `SCHEMA_VERSION` written into every manifest. We can detect output produced by older tool versions and migrate or reject as needed.

Cost: model boilerplate. Worth it.

### Why 8 stages, not fewer?

Could be folded — discover + crawl could be one async stream. Why didn't we?

- **Inspectability.** Each stage's output is on disk. If `analyze_dna` produces a weird palette, you can `cat raw/pages/_index/computed-styles.json` and check the input directly, without rerunning the crawl.
- **Resumability.** Crashing in stage 6 doesn't waste the work in stages 1–5.
- **Testability.** Each stage has clear inputs and outputs you can fixture and snapshot.

Slight performance cost (writing intermediate JSON to disk). Worth it for the debugging experience.

### Why content-hash dedupe for assets?

Same logo referenced from 8 pages → without dedupe, 8 file copies on disk (and 8 downloads). With content-hash dedupe (SHA-256, first 16 hex chars as filename), 1 file on disk, 1 download, 8 references in the asset manifest.

Bonus: if two visually identical images have different URLs (CDN versioning), we detect that.

### Why store screenshots at all? They're huge.

For the inspector primarily. Thumbnails in the index page need a visual reference. The full screenshot is also a useful "ground truth" for what the captured page actually looked like — especially useful when investigating a "the rendered HTML looks wrong" bug.

`--skip-assets` doesn't skip screenshots. Add `--no-screenshots` for that.

---

## Auth and security

### Why move credentials out of the slash command?

Slash commands appear in:
- Chat logs (potentially indefinitely)
- Telemetry (Anthropic logs prompts in some modes)
- Screen shares (you screenshot a chat to ask a colleague)
- Browser history (if your client is web-based)

`/dna-website https://x.com --password hunter2` is a credential disclosure waiting to happen. `.dna-website.env` is a file on the user's machine, gitignored, mode 0600.

### Why support Chrome MCP if Playwright can do auth?

Pure Playwright struggles with:
- SSO (Google, Okta, Azure AD — redirect chains, MFA challenges)
- Password manager autofill (1Password, Bitwarden — extension-based)
- Site anti-automation (Cloudflare, Datadome — detect headless Chrome)
- TOTP from a paired authenticator app

Chrome MCP drives a *real* Chrome that's already logged into the user's accounts, with their password manager extensions installed. Once the session is established, we export `storage_state` and hand off to headless Playwright for the bulk crawl.

### Why default-deny banking and government domains?

Three reasons:
1. **Legal.** Most jurisdictions have specific laws (CFAA in the US, Computer Misuse Act in the UK, similar elsewhere) about automated access to financial and government systems.
2. **Risk.** Even if legal, getting flagged by a banking fraud detection system is a multi-hour cleanup.
3. **Use case.** Almost no legitimate "study the design" use case requires these targets.

`--i-own-this-site` exists for the rare case (you own a small bank's website; you're rebuilding a government department's portal you maintain). Override requires typed confirmation, not just a flag.

### What gets sanitized?

From every byte written to disk:
- HTTP headers: `Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key`, `X-Auth-Token`, `X-CSRF-Token`, etc.
- URL query parameters: `password`, `secret`, `token`, `key`, `auth`, `api_key`, `access_token`, `code`, `state` (PKCE), etc.
- JSON fields matching common credential names.
- String values matching regex patterns for JWTs, GitHub PATs, Stripe keys, Slack tokens, AWS keys, etc.

See `scripts/utils.py:SENSITIVE_*` for the full lists. They're expandable — pull requests welcome for new patterns.

What we *don't* sanitize: site content. If the captured page legitimately shows a piece of text that happens to look like a JWT, that's content, not credentials, and we leave it.

---

## Performance and scope

### Why is there a default page cap of 200?

Two reasons:
1. **Crawl politeness.** Crawling thousands of pages from one IP at any rate is suspicious.
2. **Diminishing returns for design analysis.** A site's design DNA is fully present in 20–50 representative pages. The 201st page rarely adds new color or component patterns.

`--max-pages 1000` is supported. The default is conservative.

### Why is concurrency capped at 3 by default?

Authenticated apps in particular often have per-session connection limits or trigger rate-based abuse detection above 3-4 concurrent requests. Public marketing sites tolerate more. Tune per target.

### Can this crawl really big sites (10k+ pages)?

Yes, with the right config:
- `--max-pages 10000`
- `--rate-limit 1` (be polite)
- `--concurrency 2`
- `--depth 5` (or higher)
- Plan for hours, not minutes.
- Use `--resume` to handle interruptions.

But: for sites this size, the value-per-page of capture drops rapidly. Consider running on a representative subset.

---

## Limitations and known issues

### Sites with heavy client-side rendering may capture incomplete content

If the site fetches data with a delay > the per-page timeout, you'll capture the loading state. Mitigation: `--page-timeout 60` and watch the network log for in-flight requests at capture time.

### Sites behind aggressive anti-bot defenses (Cloudflare Turnstile, Datadome)

Pure headless Playwright will sometimes fail. Strategies:
1. Use `manual` auth even on public sites (you pass the challenge once, the crawl reuses the cookie).
2. Use Chrome MCP (a real Chrome is less suspicious than headless).
3. Reduce concurrency to 1.

Don't bypass — if a site is actively serving CAPTCHAs, that's a clear signal.

### Fonts loaded from CDN with restricted CORS

We capture the URL and the rendered text but can't download the file bytes for some Google Fonts and other CDN deliveries. For rebrand purposes, you'd license/re-host the font yourself anyway.

### Sites that gate content by geography

If the site behaves differently based on the visitor's region, you'll capture the experience from wherever you're running. Use a VPN if you need a specific region's experience.

---

## Future / not-yet-built

### Visual regression detection across runs

`scripts/compare.py` exists and compares JSON artifacts (design tokens, content, IA). Pixel-level diffing of screenshots is a planned future addition.

### Rebrand preview server

The inspector currently serves the captured site as-is. A future mode will let you edit `rebrand/tokens.css` and see the rendered page update live. Tracked as a v0.2 goal.

### Multi-site comparison

Currently `compare` works on two runs of the same site. Comparing different sites (your site vs. 3 competitors, side-by-side design tokens) is a planned feature.

### Headless mode for fully automated cron use

The current design assumes a human is somewhere in the loop for auth and confirmations. A `--unattended` mode that fails closed (refuses if any prompt would be needed) is on the roadmap.

---

## Meta questions

### Why so much documentation?

Because:
1. The tool does things that *could* be misused. Heavy documentation of "this is how it's safe, this is what's blocked" is part of the safety story.
2. The algorithms have non-obvious tuning constants. Without docs, the next person to touch the code will revert hard-won calibration choices.
3. The handoff target is "another agent or engineer picks this up cold." Cold handoffs need maps, not codebases.

### Why so many tests?

Because the algorithms are non-deterministic-feeling (clustering, hashing) and the output is hard to eyeball-verify. Without tests, regressions are invisible until someone notices their palette looks weird.

### Will this be maintained?

This is a scaffold + plan. Maintenance happens after v0.1.0 ships, by whoever owns the codebase. The CHANGELOG tracks the trail.
