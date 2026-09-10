"""
Bulk-capture a list of URLs via Playwright, with the full v1-pipeline-grade
treatment ported into Python:

  * Patience presets (fast/normal/patient/maximum) — bundled goto-timeout,
    networkidle, post-load settle, final settle.
  * Interactor pass (browser_scripts/interactor.js) — clicks accordions,
    tabs, details, reveal buttons, carousel-next arrows, hovers mega-menus,
    scrolls top→bottom. Hard guards skip any element whose text or class
    matches the purchase blocklist.
  * Retry with exponential backoff (3 attempts) on transient nav failures.
  * Lazy-asset extraction — img[data-src], img[data-lazy-src],
    [data-background-image], [data-bg-image-mobile], [data-gallery-bg]
    (base64 JSON), data-original, srcset variants.
  * Network-log asset discovery — every image/font/css/script URL the
    browser actually fetched, added to image_urls if missed by HTML walk.

Output per URL: outputs/<run>/_inbox/<slug>.json (compact format consumed by
scripts/save_compact.py). Optional screenshots written alongside.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from scripts.utils import is_purchase_url


# ---------------------------------------------------------------------------
# Patience presets (mirrors webapp-clone-pipeline/src/cloner/crawler.js)
# ---------------------------------------------------------------------------

WAIT_PRESETS = {
    "fast":    {"goto_ms": 20000, "idle_ms":  4000, "post_load_ms":  500, "interactor_step_ms": 200, "final_ms":   500},
    "normal":  {"goto_ms": 45000, "idle_ms": 12000, "post_load_ms": 3000, "interactor_step_ms": 500, "final_ms":  2000},
    "patient": {"goto_ms": 60000, "idle_ms": 18000, "post_load_ms": 5000, "interactor_step_ms": 800, "final_ms":  5000},
    "maximum": {"goto_ms": 90000, "idle_ms": 30000, "post_load_ms": 8000, "interactor_step_ms": 1200,"final_ms": 10000},
}


def slug_for(url: str) -> str:
    p = urlparse(url)
    path = (p.path or "/").strip("/")
    parts = path.split("/") if path else []
    if p.query:
        parts.append(re.sub(r"[=&]", "_", p.query))
    if not parts:
        return "home"
    slug = "__".join(parts).lower()
    return re.sub(r"[^a-z0-9_-]", "-", slug) or "home"


INTERACTOR_PATH = Path(__file__).parent.parent / "browser_scripts" / "interactor.js"
INTERACTOR_SRC = INTERACTOR_PATH.read_text(encoding="utf-8")


# Extractor — same as before, plus lazy-asset attrs and srcset variants.
EXTRACTOR_JS = r"""
() => {
  const ORIGIN = location.origin;
  const strip = s => !s ? s : String(s)
    .replace(/eyJ[A-Za-z0-9_\-+\/=.]{30,}/g, '[R-JWT]')
    .replace(/sk_(live|test)_[A-Za-z0-9]{16,}/g, '[R-STRIPE]')
    .replace(/pk_(live|test)_[A-Za-z0-9]{16,}/g, '[R-STRIPE]')
    .replace(/\b[A-Za-z0-9_-]{40,}\b/g, m => m.length > 40 ? '[R-LONG]' : m);

  const og={}, tw={};
  for (const m of document.querySelectorAll('meta')) {
    const p=m.getAttribute('property')||m.getAttribute('name')||'';
    const c=m.getAttribute('content')||'';
    if (!c) continue;
    if (p.startsWith('og:')) og[p.slice(3)]=strip(c);
    else if (p.startsWith('twitter:')) tw[p.slice(8)]=strip(c);
  }
  const meta = {
    url: location.href, final_url: location.href, title: document.title||'',
    description: (document.querySelector('meta[name="description"]')||{}).getAttribute &&
                 document.querySelector('meta[name="description"]').getAttribute('content') || null,
    canonical: (document.querySelector('link[rel="canonical"]')||{}).getAttribute &&
               document.querySelector('link[rel="canonical"]').getAttribute('href') || null,
    og, twitter: tw, json_ld: [],
    lang: document.documentElement.getAttribute('lang')||null,
    viewport: (document.querySelector('meta[name="viewport"]')||{}).getAttribute &&
              document.querySelector('meta[name="viewport"]').getAttribute('content') || null,
    favicon: (document.querySelector('link[rel*="icon"]')||{}).getAttribute &&
             document.querySelector('link[rel*="icon"]').getAttribute('href') || null,
    manifest_url: null
  };

  // JSON-LD blocks
  const jsonLd = [];
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try { jsonLd.push(JSON.parse(s.textContent)); } catch (_) {}
  }
  meta.json_ld = jsonLd;

  const sectionEls = [];
  for (const r of document.querySelectorAll('section, article, main')) sectionEls.push(r);
  if (!sectionEls.length && document.body) sectionEls.push(document.body);
  const seen = new WeakSet();
  const sections = [];
  for (const root of sectionEls) {
    if (seen.has(root)) continue; seen.add(root);
    let h=null, lvl=null;
    for (const t of ['h1','h2','h3','h4']) {
      const x=root.querySelector(t);
      if (x) { h=(x.textContent||'').trim().slice(0,240); lvl=parseInt(t.slice(1)); break; }
    }
    const paras = Array.from(root.querySelectorAll('p'))
      .map(p=>(p.textContent||'').trim()).filter(t=>t.length>5).slice(0,30)
      .map(t=>strip(t.slice(0,600)));
    const lks = Array.from(root.querySelectorAll('a[href]')).slice(0,50).map(a=>{
      let u=''; try{u=new URL(a.getAttribute('href'),location.href).toString();}catch(_){}
      return {text:strip((a.textContent||'').trim().slice(0,200)), href:u};
    });
    const imgs = Array.from(root.querySelectorAll('img')).slice(0,20).map(img=>{
      let src = img.getAttribute('src') || img.getAttribute('data-src')
              || img.getAttribute('data-lazy-src') || img.getAttribute('data-original') || '';
      let u=''; try { u=new URL(src,location.href).toString(); } catch(_){}
      return {src:u, alt:(img.getAttribute('alt')||'').slice(0,200), caption:null};
    });
    const ctas=[];
    for (const e of root.querySelectorAll('button, a')) {
      const cls=(typeof e.className==='string'?e.className:'').toLowerCase();
      const t=(e.textContent||'').trim();
      if (!t) continue;
      if (e.tagName!=='BUTTON' && !/btn|cta|button/.test(cls)) continue;
      let h2=null;
      if (e.tagName==='A') { try{h2=new URL(e.getAttribute('href'),location.href).toString();}catch(_){} }
      ctas.push({text:strip(t.slice(0,200)), href:h2, kind:e.tagName==='BUTTON'?'button':'link'});
      if (ctas.length>=20) break;
    }
    if (h||paras.length||lks.length||imgs.length||ctas.length) {
      sections.push({id:root.getAttribute('id')||null, heading:h, level:lvl,
        paragraphs:paras, links:lks, images:imgs, ctas});
    }
  }

  const C=new Map(),BG=new Map(),F=new Map(),S=new Map(),BC=new Map(),
        FF=new Map(),FS=new Map(),FW=new Map(),LH=new Map(),LS=new Map(),
        P=new Map(),M=new Map(),G=new Map(),R=new Map(),SH=new Map(),T=new Map();
  const BP=new Set();
  const inc=(m,v)=>{ if(!v||v==='normal'||v==='0px'||v==='none'||v==='auto') return; m.set(v,(m.get(v)||0)+1); };
  const skip=new Set(['script','style','noscript','meta','link','br','hr']);
  const all = document.body ? document.body.querySelectorAll('*') : [];
  let sampled=0;
  for (const el of all) {
    if (sampled>=5000) break;
    const t=el.tagName.toLowerCase();
    if (skip.has(t)) continue;
    const cs=getComputedStyle(el);
    inc(C,cs.color); inc(BG,cs.backgroundColor); inc(F,cs.fill); inc(S,cs.stroke); inc(BC,cs.borderColor);
    inc(FF,cs.fontFamily); inc(FS,cs.fontSize); inc(FW,cs.fontWeight); inc(LH,cs.lineHeight); inc(LS,cs.letterSpacing);
    inc(P,cs.paddingTop); inc(P,cs.paddingRight); inc(P,cs.paddingBottom); inc(P,cs.paddingLeft);
    inc(M,cs.marginTop); inc(M,cs.marginRight); inc(M,cs.marginBottom); inc(M,cs.marginLeft);
    inc(G,cs.gap); inc(R,cs.borderRadius); inc(SH,cs.boxShadow); inc(T,cs.transition);
    sampled++;
  }
  try {
    for (const ss of document.styleSheets) {
      try { for (const r of (ss.cssRules||[])) {
        if (r.media) { const x = r.media.mediaText.match(/(min|max)-width:\s*(\d+)px/g); if (x) for (const y of x) BP.add(y); }
      } } catch(_) {}
    }
  } catch(_) {}
  const tp=(m,n)=>Object.fromEntries(Array.from(m.entries()).sort((a,b)=>b[1]-a[1]).slice(0,n));
  const compact = {
    sampled,
    colors: tp(C,40), background_colors: tp(BG,40),
    fills: tp(F,20), strokes: tp(S,20), border_colors: tp(BC,20),
    font_families: tp(FF,8), font_sizes: tp(FS,24), font_weights: tp(FW,12),
    line_heights: tp(LH,16), letter_spacings: tp(LS,16),
    paddings: tp(P,24), margins: tp(M,24), gaps: tp(G,12),
    radii: tp(R,12), shadows: tp(SH,12), transitions: tp(T,10),
    breakpoints: Array.from(BP).sort()
  };

  // In-scope links — strip url-fragments and out-of-origin hosts
  const lset = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    try {
      const u = new URL(a.getAttribute('href'), location.href);
      if (u.origin === ORIGIN) { u.hash=''; lset.add(u.toString()); }
    } catch(_) {}
  }

  // Asset URLs — exhaustive walk including lazy/duda patterns.
  const iset = new Set();
  const addAbs = (raw) => { if (!raw) return; try { iset.add(new URL(raw, location.href).toString()); } catch(_){} };

  for (const img of document.querySelectorAll('img')) {
    addAbs(img.getAttribute('src'));
    addAbs(img.getAttribute('data-src'));
    addAbs(img.getAttribute('data-lazy-src'));
    addAbs(img.getAttribute('data-original'));
    addAbs(img.getAttribute('data-bg-image'));
    const srcset = img.getAttribute('srcset') || img.getAttribute('data-srcset');
    if (srcset) {
      for (const part of srcset.split(',')) {
        const url = part.trim().split(/\s+/)[0];
        if (url) addAbs(url);
      }
    }
  }
  for (const lk of document.querySelectorAll('link[href]')) {
    const rel = (lk.getAttribute('rel') || '').toLowerCase();
    if (/stylesheet|icon|preload|manifest|apple-touch/.test(rel)) addAbs(lk.getAttribute('href'));
  }
  for (const s of document.querySelectorAll('script[src]')) addAbs(s.getAttribute('src'));
  for (const v of document.querySelectorAll('video[src], video[poster], video source[src], audio source[src], source[src]')) {
    addAbs(v.getAttribute('src') || v.getAttribute('poster'));
  }
  // CSS-in-style attributes
  for (const el of document.querySelectorAll('[style]')) {
    const style = el.getAttribute('style') || '';
    for (const m of style.matchAll(/url\(\s*['"]?([^'")]+)['"]?\s*\)/g)) addAbs(m[1]);
  }
  // Inline <style> blocks
  for (const s of document.querySelectorAll('style')) {
    const css = s.textContent || '';
    for (const m of css.matchAll(/url\(\s*['"]?([^'")]+)['"]?\s*\)/g)) addAbs(m[1]);
  }
  // Duda lazy-bg attributes
  for (const el of document.querySelectorAll('[data-background-image], [data-bg-image], [data-bg-image-mobile], [data-bg-image-tablet]')) {
    addAbs(el.getAttribute('data-background-image'));
    addAbs(el.getAttribute('data-bg-image'));
    addAbs(el.getAttribute('data-bg-image-mobile'));
    addAbs(el.getAttribute('data-bg-image-tablet'));
  }
  // data-gallery-bg is a base64-encoded JSON with slides[].url
  for (const el of document.querySelectorAll('[data-gallery-bg]')) {
    let raw = el.getAttribute('data-gallery-bg');
    if (!raw) continue;
    try {
      const decoded = atob(raw);
      const parsed = JSON.parse(decoded);
      const slides = parsed.slides || parsed.images || [];
      for (const sl of slides) {
        const u = (sl && (sl.url || sl.src)) || '';
        if (u) addAbs(u);
      }
    } catch(_) {}
  }

  const walk = (el, d) => d > 4 ? null : ({
    tag: el.tagName ? el.tagName.toLowerCase() : null,
    id: el.id || null,
    classes: (typeof el.className === 'string' ? el.className.split(/\s+/).filter(Boolean) : []).slice(0, 6),
    role: el.getAttribute ? el.getAttribute('role') : null,
    children: Array.from(el.children || []).slice(0, 12).map(c => walk(c, d + 1)).filter(x => x)
  });

  return {
    url: location.href, final_url: location.href,
    http_status: 200, duration_ms: 0,
    meta, sections,
    compact_styles: compact,
    links: Array.from(lset).sort(),
    image_urls: Array.from(iset).sort(),
    dom: document.body ? walk(document.body, 0) : null
  };
}
"""


async def capture_url(page, url: str, waits: dict, interactor_src: str) -> tuple[dict, dict]:
    """Navigate + interact + extract. Returns (capture_dict, network_log).

    network_log is the list of all browser-issued URLs during the page's
    lifetime. We harvest it from a request listener attached at context level
    by the caller — see main_async().
    """
    started_at = asyncio.get_event_loop().time()
    resp = await page.goto(url, wait_until="load", timeout=waits["goto_ms"])
    try:
        await page.wait_for_load_state("networkidle", timeout=waits["idle_ms"])
    except Exception:
        pass
    await page.wait_for_timeout(waits["post_load_ms"])

    interactions: dict = {}
    try:
        interactions = await page.evaluate(
            f"({interactor_src})({{stepMs: {waits['interactor_step_ms']}}})"
        )
    except Exception as e:
        interactions = {"error": str(e)[:200]}

    # Final settle — let IntersectionObserver + lazy-load content paint.
    try:
        await page.evaluate("() => window.scrollTo(0, 0)")
        await page.wait_for_timeout(waits["final_ms"])
        await page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass

    data = await page.evaluate(EXTRACTOR_JS)
    if resp is not None:
        data["http_status"] = resp.status
        data["final_url"] = page.url
    data["slug"] = slug_for(url)
    data["duration_ms"] = int((asyncio.get_event_loop().time() - started_at) * 1000)
    data["interactions"] = interactions

    # Grab the post-interactor rendered HTML too. This is the SAME content
    # we'd otherwise have to merge from a v1 capture — Playwright direct
    # has no cookie/token filter, unlike Chrome MCP. Token-shape sweep
    # before writing so any inline secrets get redacted at capture time.
    try:
        raw_html = await page.content()
        data["rendered_html"] = _strip_obvious_secrets(raw_html)
    except Exception as e:
        data["rendered_html"] = None
        data["rendered_html_error"] = str(e)[:200]

    return data


_SENSITIVE_INLINE_PATTERNS = [
    (re.compile(r"eyJ[A-Za-z0-9_\-+/=.]{20,}\.[A-Za-z0-9_\-+/=.]{6,}\.[A-Za-z0-9_\-+/=.]{6,}"), "[REDACTED-JWT]"),
    (re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{16,}"), "[REDACTED-STRIPE]"),
    (re.compile(r"pk_(?:live|test)_[A-Za-z0-9]{16,}"), "[REDACTED-STRIPE]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "[REDACTED-GITHUB]"),
    (re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"), "[REDACTED-SLACK]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-+/=]{20,}"), "Bearer [REDACTED]"),
]


def _strip_obvious_secrets(html: str) -> str:
    for pat, repl in _SENSITIVE_INLINE_PATTERNS:
        html = pat.sub(repl, html)
    return html


async def capture_with_retry(page, url: str, waits: dict, interactor_src: str, attempts: int = 3) -> dict:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            data = await capture_url(page, url, waits, interactor_src)
            return data
        except Exception as e:
            last_exc = e
            # Don't retry "real 404" patterns
            msg = str(e).lower()
            if "net::err_name_not_resolved" in msg or "404" in msg:
                break
            backoff = 1.5 * (2 ** (attempt - 1))
            print(f"  attempt {attempt}/{attempts} failed: {e}; retrying in {backoff:.1f}s")
            await asyncio.sleep(backoff)
    raise last_exc if last_exc else RuntimeError("retry exhausted")


def merge_network_assets(data: dict, network_urls: set[str], origin: str) -> None:
    """Add same-origin assets from the network log that aren't already in
    data['image_urls']. Filters out HTML pages, analytics hosts."""
    SAME_ORIGIN_OR_CDN = lambda u: (
        urlparse(u).netloc == urlparse(origin).netloc
        or urlparse(u).netloc.endswith(".kindskiptracing.com")
    )
    ASSET_EXTS = {
        ".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg", ".ico",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".css", ".js", ".mjs",
        ".mp4", ".webm", ".mov", ".mp3", ".wav", ".ogg",
    }
    existing = set(data.get("image_urls") or [])
    additions = []
    for u in network_urls:
        if u in existing:
            continue
        if is_purchase_url(u):
            continue
        try:
            p = urlparse(u)
            ext = ""
            if "." in p.path:
                ext = "." + p.path.rsplit(".", 1)[-1].lower().split("?")[0]
            if ext not in ASSET_EXTS:
                continue
            additions.append(u)
        except Exception:
            continue
    if additions:
        data["image_urls"] = sorted(existing | set(additions))


async def main_async(
    urls: list[str], out_dir: Path, patience: str,
    screenshots: bool, user_data_dir: str | None,
):
    waits = WAIT_PRESETS.get(patience, WAIT_PRESETS["normal"])
    out_dir.mkdir(parents=True, exist_ok=True)
    inbox = out_dir / "_inbox"
    inbox.mkdir(exist_ok=True)

    cap_meta = {
        "captured_at": None,
        "patience": patience,
        "viewport": {"width": 1440, "height": 900},
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "max_pages": len(urls),
        "concurrency": 1,
        "screenshots_full_page": True,
        "interactor": True,
        "lazy_asset_extraction": True,
        "network_log_asset_discovery": True,
        "url_count": len(urls),
    }

    async with async_playwright() as p:
        if user_data_dir:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,
                viewport={"width": 1440, "height": 900},
            )
        else:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=cap_meta["user_agent"],
            )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # Network listener — accumulate URLs per page navigation.
        current_urls: set[str] = set()
        def on_request(req):
            try: current_urls.add(req.url)
            except Exception: pass
        ctx.on("request", on_request)

        from datetime import datetime
        cap_meta["captured_at"] = datetime.utcnow().isoformat()

        for url in urls:
            if is_purchase_url(url):
                print(f"SKIP (purchase URL): {url}")
                slug = slug_for(url)
                (inbox / f"{slug}.skip.json").write_text(json.dumps({
                    "url": url, "slug": slug,
                    "status": "skipped_purchase_url",
                    "reason": "matches purchase URL pattern",
                }, indent=2))
                continue
            print(f"GET {url} (patience={patience})")
            current_urls.clear()
            try:
                data = await capture_with_retry(page, url, waits, INTERACTOR_SRC, attempts=3)
                # Merge network-log assets
                origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                merge_network_assets(data, current_urls, origin)
                # Capture metadata per page
                data["capture_meta"] = {
                    "patience": patience,
                    "interactions": data.get("interactions"),
                }
                slug = data.get("slug") or slug_for(url)
                inbox_path = inbox / f"{slug}.json"
                inbox_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                ix = data.get("interactions") or {}
                print(f"  -> {slug}  sections={len(data.get('sections') or [])} links={len(data.get('links') or [])} "
                      f"assets={len(data.get('image_urls') or [])} sampled={data.get('compact_styles',{}).get('sampled')} "
                      f"clicked={ix.get('clicked',0)} revealed={ix.get('sectionsRevealed',0)} "
                      f"skipped_purchase={ix.get('skippedPurchase',0)}")
                if screenshots:
                    shot = inbox / f"{slug}.png"
                    try:
                        await page.screenshot(path=str(shot), full_page=True)
                    except Exception as e:
                        print(f"  screenshot failed: {e}")
            except Exception as e:
                print(f"  ERROR {url}: {e}")
                slug = slug_for(url)
                (inbox / f"{slug}.error.json").write_text(json.dumps({
                    "url": url, "slug": slug, "status": "error",
                    "error": str(e)[:500],
                }, indent=2))
        # Write capture-config metadata once, for reproducibility.
        (out_dir / "capture_config.json").write_text(json.dumps(cap_meta, indent=2), encoding="utf-8")
        if user_data_dir:
            await ctx.close()
        else:
            await ctx.close()
            await browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--urls", nargs="+", required=True)
    ap.add_argument("--screenshots", action="store_true")
    ap.add_argument("--patience", default="normal", choices=list(WAIT_PRESETS.keys()),
                    help="fast=20s/4s; normal=45s/12s; patient=60s/18s; maximum=90s/30s")
    ap.add_argument("--user-data-dir",
                    help="Optional persistent profile dir (use for authenticated runs)")
    args = ap.parse_args()
    asyncio.run(main_async(
        args.urls,
        Path(args.out).resolve(),
        args.patience,
        args.screenshots,
        args.user_data_dir,
    ))


if __name__ == "__main__":
    main()
