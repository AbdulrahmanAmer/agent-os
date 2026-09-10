# Examples

> Worked examples for the three most common use cases. Copy a recipe, adapt it.

---

## Recipe 1 — Public marketing site

You want to study a competitor's marketing site for a redesign. No auth.

### Setup
```bash
cd ~/projects
git clone <this-repo> dna-website
cd dna-website
make install
```

### Run
```bash
python -m scripts.run https://competitor.com \
    --depth 3 \
    --max-pages 30 \
    --mobile-also \
    --output ./outputs/competitor-2026-05
```

Expected wall-clock: 3–5 minutes for a typical 30-page site.

### Inspect
```bash
python -m scripts.serve ./outputs/competitor-2026-05
# Opens http://localhost:7777
```

### Read
- `outputs/competitor-2026-05/REPORT.md` — high-level summary
- `outputs/competitor-2026-05/analysis/design-tokens.json` — extracted tokens
- `outputs/competitor-2026-05/analysis/component-patterns.json` — repeated UI patterns
- `outputs/competitor-2026-05/analysis/content-inventory.json` — page content

### Tip
If the site uses heavy JavaScript (likely for marketing sites with hero animations), watch the network log on a sample page. If you see API calls that didn't complete in the capture, bump the per-page timeout:

```bash
python -m scripts.run https://competitor.com --page-timeout 60 ...
```

---

## Recipe 2 — Authenticated dashboard (SaaS your team uses)

You're rebuilding the UI for your team's internal admin tool. Logged-in-only.

### One-time setup: auth profile

Create `.dna-website.env` in the project root (it's gitignored):

```ini
[default]
url = https://admin.internal.example.com
strategy = manual
post_login_url_pattern = ^https://admin\.internal\.example\.com/dashboard
verify_session_url = https://admin.internal.example.com/api/me
verify_session_success = "id":\s*\d+
```

The `manual` strategy means: tool opens Chrome, you log in by hand (SSO, password manager, whatever), then press Enter in the terminal. The tool captures the resulting session and uses it for the headless crawl.

### Run
```bash
python -m scripts.run https://admin.internal.example.com \
    --auth default \
    --depth 4 \
    --max-pages 100 \
    --rate-limit 1 \
    --output ./outputs/admin-2026-05
```

The `--rate-limit 1` is gentle because internal tools rarely have generous rate limits and you don't want to wake up the SRE team.

### Watch for
- A long crawl. Authenticated apps are usually bigger than marketing sites.
- The session may expire mid-crawl. If you see auth redirects in `captures.json`, re-auth and use `--resume`:
  ```bash
  python -m scripts.run https://admin.internal.example.com --auth default --resume --output ./outputs/admin-2026-05
  ```

### Inspect
Open the inspector to walk through the captured UI. Click into pages with complex state — you'll see what the screen looked like at capture time.

### Rebrand
Open `outputs/admin-2026-05/rebrand/README.md`. Follow the steps. The token template lets you swap the brand colors without touching the (often messy) underlying HTML.

---

## Recipe 3 — E-commerce product catalog

You want to study a competitor's product detail page design. Public, but with lots of pages.

### Run
```bash
python -m scripts.run https://shop.example.com \
    --depth 2 \
    --max-pages 200 \
    --rate-limit 1 \
    --max-asset-size 10 \
    --output ./outputs/shop-2026-05
```

Notes:
- `--rate-limit 1` is firm. E-commerce sites have aggressive anti-bot defenses; being polite is also being safe.
- `--max-asset-size 10` caps assets at 10 MB so you don't accidentally download a 4K hero video for every page.
- `--depth 2` from the home page is usually enough to reach product detail pages without descending into pagination hell.

### Component pattern analysis
After the run, the most valuable file is:
```
outputs/shop-2026-05/analysis/component-patterns.json
```

Look for the `card` and `tile` role guesses with high occurrence counts. Those are the product cards. The `examples` array has the rendered HTML for the first few instances — useful for understanding the structure without opening browser dev tools on every page.

### When the site has anti-bot defenses

Some e-commerce sites use Cloudflare Bot Manager, Datadome, etc. Pure headless Playwright will sometimes hit a CAPTCHA challenge. Strategies:

1. **Use the `manual` auth strategy** even for non-auth sites. The user passes the bot check once, then the headless crawl uses the resulting cookie.
2. **Reduce concurrency**: `--concurrency 1` makes the traffic pattern look more human.
3. **Don't bypass.** If the site is actively serving CAPTCHAs, take the hint. Use only the data you've already gathered.

---

## Recipe 4 — One-off, single-page inspection

You just want to dump the design tokens for one URL.

```bash
python -m scripts.run https://example.com/specific-page \
    --depth 0 \
    --max-pages 1 \
    --skip-assets \
    --output ./outputs/single-page
```

`--depth 0` means "just the URL given, no link following." `--skip-assets` skips the asset pipeline entirely, which is fine when you only want design tokens. Should complete in ~10–15 seconds.

---

## Recipe 5 — Tracking site changes over time

You're a designer who wants to know when a tool you use updates its UI.

```bash
# Monday
python -m scripts.run https://tool.example.com --output ./outputs/tool-2026-05-11

# A month later
python -m scripts.run https://tool.example.com --output ./outputs/tool-2026-06-11

# Diff
python -m scripts.compare ./outputs/tool-2026-05-11 ./outputs/tool-2026-06-11 --out tool-changes.md
```

Open `tool-changes.md`. You get a list of:
- Pages added/removed
- Design tokens changed (brand colors, neutrals, type ratio, spacing base)
- Assets added/removed
- Component patterns changed

This is most useful when you're watching for an enterprise tool's redesign or trying to learn from how a competitor evolves their design system.

---

## Anti-patterns (don't do these)

### Crawling a site that hasn't said you can

If a site has a `robots.txt` that disallows a path, or its terms of service prohibit automated access, don't `--ignore-robots`. This tool isn't the right hammer for that nail.

### Storing real credentials in `.dna-website.env`

If your auth strategy is `cookie_paste` or `manual`, you should never need a password in the file. The few cases where `automated` is appropriate (CI auth checks, your own dev environment) should use a per-environment secret manager and short-lived tokens, not committed text files.

### Treating outputs as deployable

The captured HTML is reference material. The CSS includes vendor prefixes and inline styles that won't fit your tech stack. The JS is the original site's code, which you don't have the rights to use. Always rebuild.

### Re-running daily on the same site

Most sites barely change month-to-month. Daily re-runs are wasteful and look suspicious in access logs. Once a quarter is plenty for most monitoring use cases.

---

## Where to ask for help

Stuck on a recipe? Open `references/troubleshooting.md` first — every known failure mode is documented there. If you find a new one, add it.
