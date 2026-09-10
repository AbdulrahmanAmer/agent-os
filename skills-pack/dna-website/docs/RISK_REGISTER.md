# Risk register

> Every risk we've identified, the impact, the likelihood, the current mitigation, and the status. Updated each milestone.

---

## Legend

| Symbol | Meaning |
|---|---|
| 🛡️ | Mitigated (mechanism exists, tested) |
| 🚧 | Partially mitigated (mechanism exists, needs hardening) |
| ⚠️ | Identified, not yet mitigated |
| ⛔ | Out of scope (deliberately not addressed) |

---

## Legal & ethical risks

### R1. Crawling a site without authorization

| | |
|---|---|
| **Impact** | High — legal liability, banned IPs, reputational harm |
| **Likelihood** | Medium — easy mistake to make |
| **Mitigation** | 🛡️ Blocked categories (banking, govt, healthcare, dating) require `--i-own-this-site` plus typed confirmation. robots.txt honored by default. SKILL.md preflight checklist asks user to confirm legitimacy. |
| **Residual risk** | The user can still lie or be wrong about authorization. Out-of-scope: we can't verify true ownership remotely. |
| **Status** | 🛡️ |

### R2. Re-publishing captured content without rights

| | |
|---|---|
| **Impact** | High — copyright infringement |
| **Likelihood** | Low if docs are read |
| **Mitigation** | 🛡️ Output is explicitly framed as "reference material, not deployable" throughout. Inspector serves locally only. README, FAQ, and rebrand README all repeat this point. |
| **Residual risk** | A motivated user can `cp -r` the output to their web server. We don't prevent it; we make the right path easier. |
| **Status** | 🛡️ |

### R3. Capturing PII the user didn't realize was there

| | |
|---|---|
| **Impact** | High — GDPR / privacy violations |
| **Likelihood** | Medium — authenticated dashboards often have user data |
| **Mitigation** | 🚧 Network log sanitization strips known sensitive headers, query params, and JSON fields. HTML content sanitization is shallow — we strip credentials but leave other content as-is. |
| **Residual risk** | If a user's dashboard renders other users' names/emails/etc., those land in the captured HTML and the inspector renders them. |
| **Action** | M12 deliverable: add an optional `--scrub-pii` mode that runs an NLP pass on captured text and redacts likely PII. |
| **Status** | 🚧 |

### R4. Bypassing site rate limits causing service degradation

| | |
|---|---|
| **Impact** | Medium — annoys site owners; possible legal issue under CFAA-like laws |
| **Likelihood** | Low with defaults |
| **Mitigation** | 🛡️ Default 2 req/s. Token-bucket limiter shared across crawl and assets. M12 includes a rate-limiter stress test. |
| **Residual risk** | User can override with `--rate-limit 50`. We don't prevent. |
| **Status** | 🛡️ |

---

## Security risks

### R5. Credentials leaking to disk

| | |
|---|---|
| **Impact** | Critical — full account compromise |
| **Likelihood** | Without mitigation: certain |
| **Mitigation** | 🛡️ Three-layer defense: (1) `.dna-website.env` is the only legal credential location and is gitignored; (2) every log/output passes through `sanitize_*`; (3) pre-commit hook scans for credentials in staged files. |
| **Testing** | M1 fuzz test: 100 random payloads with embedded JWTs, API keys, tokens — verify zero leakage. |
| **Status** | 🛡️ (pending M1 fuzz test) |

### R6. Credentials leaking via terminal output

| | |
|---|---|
| **Impact** | High — visible in screen-shared sessions, recorded chats |
| **Likelihood** | Without mitigation: medium |
| **Mitigation** | 🛡️ Slash command never accepts inline passwords. Auth profile loader uses `safe_repr` that redacts the password field. `--verbose` mode also sanitizes. |
| **Status** | 🛡️ |

### R7. Captured session being usable beyond the tool's run

| | |
|---|---|
| **Impact** | High — anyone with disk access can replay the captured session |
| **Likelihood** | Medium — sessions can live on disk for hours |
| **Mitigation** | 🛡️ `storage_state.json` written mode 0600. Default location under `.session/` which is gitignored. Auto-clean option `--cleanup-session-on-exit` in CLI. |
| **Residual risk** | Disk forensics on shared machines could recover. Out of scope. |
| **Status** | 🛡️ |

### R8. SSRF via target URL

| | |
|---|---|
| **Impact** | Low — this is a CLI tool, not a server |
| **Likelihood** | Low |
| **Mitigation** | 🚧 URL validation rejects file://, javascript:, data:, gopher:, etc. Default allows only http/https. |
| **Residual risk** | User could point at http://localhost:8000/admin if they're running other services. They'd be attacking themselves. |
| **Status** | 🚧 |

### R9. Cross-origin asset fetching pulling data we shouldn't have

| | |
|---|---|
| **Impact** | Medium — accidentally archiving third-party content |
| **Likelihood** | Medium — most sites use CDNs |
| **Mitigation** | 🛡️ Asset domain is checked against blocked-categories. Asset manifest records origin. `--no-third-party-assets` flag skips them. |
| **Status** | 🛡️ |

### R10. Malicious target injects scripts that exfiltrate

| | |
|---|---|
| **Impact** | Medium — if the target site is hostile, injected JS could attempt to read other tabs, sessions, etc. |
| **Likelihood** | Low — requires target to be specifically malicious |
| **Mitigation** | 🛡️ Playwright runs in isolated browser contexts. No extensions. New profile per run. Network egress sanitized in capture. |
| **Status** | 🛡️ |

---

## Correctness risks

### R11. Color clustering produces unstable output across runs

| | |
|---|---|
| **Impact** | Medium — undermines trust in design tokens |
| **Likelihood** | High without seeding |
| **Mitigation** | 🛡️ scikit-learn KMeans seeded with `random_state=42`. M5 acceptance: 3 identical runs produce identical output. |
| **Status** | 🛡️ |

### R12. Component pattern detection over-clusters (false positives)

| | |
|---|---|
| **Impact** | Medium — pollutes the component catalog |
| **Likelihood** | Medium |
| **Mitigation** | 🚧 `COMPONENT_RECURSION_DEPTH=3` limits structural matching. `COMPONENT_MIN_OCCURRENCE=3` filters one-offs. M8 calibration validates against real e-commerce site. |
| **Residual risk** | Sites with very uniform layouts may still over-cluster. Manual review of `component-patterns.json` recommended. |
| **Status** | 🚧 |

### R13. Component pattern detection under-clusters (false negatives)

| | |
|---|---|
| **Impact** | Low — missing patterns just means fewer entries |
| **Likelihood** | Medium |
| **Mitigation** | 🚧 Acknowledged in FAQ. Future: similarity-based clustering with a delta threshold rather than exact hash match. |
| **Status** | 🚧 |

### R14. Typography scale detection fails on irregular sites

| | |
|---|---|
| **Impact** | Low — `scale_ratio` reported as `null` |
| **Likelihood** | Medium — many sites don't use clean ratios |
| **Mitigation** | 🛡️ Algorithm tries common ratios (1.067, 1.125, 1.2, 1.25, 1.333, 1.414, 1.5, 1.618) with tolerance. Returns null if no match. Documentation describes this. |
| **Status** | 🛡️ |

### R15. Spacing GCD detection corrupted by outliers

| | |
|---|---|
| **Impact** | Medium — `base_px` reported as 1 (useless) |
| **Likelihood** | Medium |
| **Mitigation** | 🛡️ Pre-filter: only values appearing ≥ `SPACING_MIN_OCCURRENCE=3` times feed into GCD. Plus a max GCD cap (default 16) — if "GCD" comes out larger, something is wrong, drop to a fallback. |
| **Status** | 🛡️ |

---

## Operational risks

### R16. Long-running crawl interrupted, work lost

| | |
|---|---|
| **Impact** | Medium — wasted time |
| **Likelihood** | High — networks fail |
| **Mitigation** | 🛡️ `manifest.partial.json` written after each page. `--resume` skips completed work. |
| **Testing** | M3 acceptance: kill a 50-page crawl at page 25, resume completes pages 25–50 only. |
| **Status** | 🛡️ |

### R17. Disk fills up mid-run

| | |
|---|---|
| **Impact** | Medium — corrupt output |
| **Likelihood** | Low — output is usually < 1GB |
| **Mitigation** | 🚧 Doctor checks free disk on startup. Per-asset `--max-asset-size` (default 50MB). |
| **Action** | M12: add periodic disk-free check during crawl with graceful pause-and-warn at < 1GB free. |
| **Status** | 🚧 |

### R18. Memory blowup on huge pages

| | |
|---|---|
| **Impact** | Medium — crashes |
| **Likelihood** | Low |
| **Mitigation** | 🛡️ Streaming asset downloads (no buffering of full file in memory). Computed styles capped at `MAX_ELEMENTS_PER_PAGE=5000`. |
| **Status** | 🛡️ |

### R19. Chrome MCP unavailable

| | |
|---|---|
| **Impact** | Low — falls back to headed Playwright |
| **Likelihood** | Medium — depends on user's environment |
| **Mitigation** | 🛡️ Auth strategy fallback ladder: chrome_mcp → manual → cookie_paste → automated. Each fallback documented in `references/auth_strategies.md`. |
| **Status** | 🛡️ |

### R20. Per-page capture hangs indefinitely

| | |
|---|---|
| **Impact** | Medium — crawl never completes |
| **Likelihood** | Medium — SPAs can hang waiting for never-completing requests |
| **Mitigation** | 🛡️ Hard `--page-timeout` (default 30s). Custom network-idle detector with hard cap. Per-asset `--asset-timeout` (default 30s). |
| **Status** | 🛡️ |

---

## Process risks

### R21. Tuning constants drift over time, breaking calibration

| | |
|---|---|
| **Impact** | Medium — output quality degrades |
| **Likelihood** | High without discipline |
| **Mitigation** | 🛡️ All tuning constants in named module-level variables. `references/calibration.md` documents rationale. Snapshot tests in `tests/test_analyze_dna.py` catch unintended changes. |
| **Status** | 🛡️ |

### R22. New contributor disables a security check to make a test pass

| | |
|---|---|
| **Impact** | High |
| **Likelihood** | Low if PRs are reviewed |
| **Mitigation** | 🛡️ CLAUDE.md and PROMPTS.md explicitly call this out as an anti-pattern. Pre-commit hook runs sanitization tests. |
| **Status** | 🛡️ |

### R23. Schema change breaks downstream code without notice

| | |
|---|---|
| **Impact** | Medium |
| **Likelihood** | Medium |
| **Mitigation** | 🛡️ `SCHEMA_VERSION` constant. Every output manifest records it. Bump triggers `references/data_contracts.md` update (enforced in PROMPTS.md anti-patterns). |
| **Status** | 🛡️ |

---

## Out-of-scope risks (deliberately not addressed)

### R-OOS-1. User intentionally violates a site's terms of service

The tool can't enforce ToS. We provide enough friction (confirmations, defaults, framing) to make accidental violations hard. Intentional violations are the user's responsibility.

### R-OOS-2. Two-factor auth without manual intervention

Fully unattended automated 2FA is out of scope. We support TOTP from a shared seed in the env profile, but the safer path is the manual or chrome_mcp strategy where the user completes 2FA in the visible browser.

### R-OOS-3. CAPTCHA solving

Never. If a site is serving CAPTCHAs, the right answer is "use a different source of design reference" or "log in manually once and use the cookie."

### R-OOS-4. JavaScript reverse-engineering

We capture network calls (sanitized) and rendered DOM. We don't attempt to reconstruct application logic from minified JS. That's a different tool.

### R-OOS-5. Real-time monitoring

This is a snapshot tool. For ongoing monitoring, use `scripts/compare.py` to diff two runs, or build something purpose-built on top.

---

## How to update this register

- New risk identified → add a row, set status `⚠️`, file a follow-up issue.
- Risk mitigated → update status, link to the test or mechanism that mitigates it.
- Risk re-evaluated (e.g. likelihood changed) → update fields, note the reason in the CHANGELOG.

Review the full register before every milestone close.
