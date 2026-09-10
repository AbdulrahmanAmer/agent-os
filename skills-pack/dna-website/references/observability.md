# Observability

> How to know what the tool is doing, what went wrong, and how to debug it after the fact.

---

## Logging

### Configuration

Logging is configured once at the top of `scripts/run.py`. Two handlers:

1. **Console handler** — colored via `rich`, INFO level by default, DEBUG with `--verbose`.
2. **File handler** — plain text, always DEBUG, written to `<output_dir>/run.log`.

Every module gets a logger via `log = logging.getLogger(__name__)`. The module name (e.g., `scripts.crawl`) is part of every log line so you can grep for issues in a single stage.

### Log format

```
2026-05-11 14:23:08 [INFO] scripts.crawl: Capturing https://example.com/about (slug=about, depth=1)
2026-05-11 14:23:09 [DEBUG] scripts.crawl: Navigated to https://example.com/about in 847ms (http=200)
2026-05-11 14:23:12 [WARN] scripts.download_assets: Asset oversize, skipping: https://example.com/video.mp4 (84.2 MB > 50.0 MB)
2026-05-11 14:23:15 [ERROR] scripts.crawl: Capture failed for https://example.com/profile: TimeoutError(navigation)
```

### Levels — when to use which

| Level | When |
|---|---|
| ERROR | A page/asset/operation failed and the run will produce incomplete output |
| WARN  | Something unexpected happened but we recovered (retry succeeded, fallback used) |
| INFO  | Stage transitions, per-page progress, end-of-stage summaries |
| DEBUG | Per-request timing, internal decisions (silhouette score chosen, etc.) |

Don't log credentials. Ever. Use `sanitize_headers` / `sanitize_url` before logging anything containing user data.

---

## The run manifest

`<output_dir>/manifest.json` is the canonical record of a run. Schema in `scripts/models.py:RunManifest`. Contains:

- Start and end timestamps
- Schema version
- Config (with credentials redacted)
- Completed stages, in order
- Per-stage timing
- Counts (pages captured, assets downloaded, etc.)
- Warnings list

A finished run with `manifest.json` present is the only state we consider "successful." A run with only `manifest.partial.json` is in-progress or aborted.

---

## Partial manifests (resume support)

After every page in the crawl stage and every batch of 10 assets, the orchestrator writes `<output_dir>/manifest.partial.json` with:

```json
{
  "started_at": "2026-05-11T14:23:00",
  "current_stage": "crawl",
  "completed_slugs": ["home", "about", "blog"],
  "completed_asset_hashes": ["abc123...", "def456..."]
}
```

When `--resume` is set, the orchestrator reads this on startup and skips already-completed work. After all stages succeed, `manifest.partial.json` is removed and `manifest.json` is written.

The crawl stage is the most expensive and benefits most from resume. The analysis stages are cheap enough to always re-run — there's no per-element checkpointing in those.

---

## Metrics

We don't ship a metrics backend. There's no Prometheus, no OpenTelemetry. The tool runs locally; metrics in the user's tracking system make no sense.

What we DO provide for retrospective analysis:

### Per-page timing in `captures.json`

Every capture has `duration_ms`. Compute the distribution after a run:

```python
import json, statistics
caps = json.load(open("dna-output/<run>/captures.json"))["captures"]
times = [c["duration_ms"] for c in caps if c["status"] == "ok"]
print(f"median: {statistics.median(times)}ms, p95: {sorted(times)[int(len(times)*0.95)]}ms")
```

### Per-stage timing in `manifest.json`

```json
{
  "stage_timings_ms": {
    "preflight": 240,
    "auth": 12000,
    "discover": 8400,
    "crawl": 187000,
    "download_assets": 92000,
    "analyze_dna": 4200,
    "analyze_content": 800,
    "build_rebrand": 350,
    "report": 1100
  }
}
```

If a run feels slow, this is the first place to look.

### Network log per page

`raw/pages/<slug>/network-log.json` has every HTTP request from that page's capture. Each entry has `duration_ms`, `status`, `response_size`. If a page is slow, sort its network log by duration and you'll usually find the culprit (some third-party tag, an unoptimized API call).

---

## What we deliberately do NOT track

- **User behavior analytics.** No clicks, no time-on-page, no funnels. This is a local tool.
- **Telemetry to Anthropic or anyone else.** The tool makes no outbound calls except to the target site.
- **PII from the user's machine.** No username, hostname, IP, mac address, etc. ever leave the machine — they don't even appear in the artifacts.

If you find yourself adding "phoning home" to anything in this codebase, that's a no.

---

## Debugging recipes

### "The crawler froze on page X"

1. Look at `run.log` for the last entries before the freeze.
2. Check if it's a `wait_until="networkidle"` timeout — these are the most common.
3. Look at `raw/pages/<slug>/network-log.json` (if it was written before the freeze). Usually a long-poll or websocket connection.
4. Mitigation: in `scripts/crawl.py`, the page wait already falls back to `domcontentloaded` after a `networkidle` timeout. If that's not enough, the page might need a custom wait (use `--per-page-wait <selector>`, currently TODO).

### "The colors all look wrong"

1. Open `analysis/color-palette.json`. Look at `raw_clusters`. How many?
2. If < 4, the analyzer didn't find enough color diversity. Probably the computed-styles capture missed elements.
3. Open `raw/pages/<slug>/computed-styles.json`. Count entries. If much less than the visible page, the DOM walker stopped early (5000-element cap).
4. If clusters look right but classification is wrong, check `NEUTRAL_SATURATION_MAX`, `BRAND_FREQ_MULTIPLIER`, `ACCENT_SATURATION_MIN` in `scripts/analyze_dna.py`. These are the knobs.

### "The crawl says 'completed' but pages are missing"

1. Check `captures.json` — `total` vs `successful` vs `failed`.
2. For each failure, look at `error_message`.
3. Most common: a route was discovered but is behind a login redirect, and the session expired mid-crawl. Re-auth and run with `--resume`.

### "Assets are downloading but image paths are broken in the inspector"

1. Open the inspector page that's missing images.
2. View source on the rewritten HTML. Are the `<img src>` paths pointing at `../../raw/assets/`?
3. If yes → the asset isn't at that path. Check `asset_manifest.json` for that URL. Probably a `download_status="failed"` entry.
4. If no → the rewriter missed it. Check `scripts/utils.py:rewrite_html_asset_paths`. The URL probably has an unusual form (data URI? blob:? signed CloudFront URL with rotating signature?). Add a case to the rewriter.

---

## Profiling

For algorithm-heavy work in `analyze_dna.py`:

```bash
python -m cProfile -o run.prof -m scripts.run https://small-site.com
python -m pstats run.prof
# In pstats: 'sort cumulative' then 'stats 30'
```

For I/O-heavy stages (crawl, download_assets), use `aiohttp`'s built-in trace config or just inspect the per-page timings in `captures.json`.

---

## When to add a new logging line

- Stage start/end: yes (already there)
- Per-page progress: yes (already there)
- Tuning constant chosen: DEBUG only
- Loop iteration: NO (DEBUG only, and only if you really need it)
- Inside hot loops: NO — use sampling or move to a profile run
