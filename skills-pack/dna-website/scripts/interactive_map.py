"""
Walk every captured HTML in raw/pages/<slug>/rendered.html and produce
analysis/interactive-map.json — an exhaustive inventory of interactive
elements per route plus an aggregate.

Python port of webapp-clone-pipeline/src/cloner/interactive-map.js.

Output shape (matches the JS version so v1 consumers keep working):

  {
    "metadata": { source_url, generated_at, agent, route_count },
    "routes": [{ url, slug, title, links, buttons, forms, iframes,
                 accordions, tabs }],
    "aggregate": {
      total_links, total_buttons, total_forms, total_iframes,
      total_accordions, total_tabs,
      external_destinations, analytics_destinations,
      same_origin_form_actions, cross_origin_form_actions,
      iframe_purposes
    }
  }

Why we have this: design analyzers need to know what a page DOES, not just
how it LOOKS. The links/buttons/forms/iframes per route feed into:
  - REPORT.md "interactive surface" sections
  - rebrand/swap-map.json's CTA placeholder mapping
  - downstream rebuild agents who need to wire up the same interactions
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


ANALYTICS_HOSTS = {
    "google-analytics.com", "googletagmanager.com", "connect.facebook.net",
    "hotjar.com", "clarity.ms", "doubleclick.net", "segment.io",
    "mixpanel.com", "amplitude.com", "fullstory.com", "matomo.org",
    "googleadservices.com", "stripe.com", "m.stripe.com", "m.stripe.network",
    "fpjs.io",
}


def classify_href(href: str, source_origin: str) -> dict:
    if not href:
        return {"kind": "empty"}
    if href.startswith("tel:"):
        return {"kind": "phone", "value": href[4:]}
    if href.startswith("mailto:"):
        return {"kind": "email", "value": href[7:]}
    if href.startswith("javascript:"):
        return {"kind": "javascript", "value": href}
    if href.startswith("#"):
        return {"kind": "anchor", "value": href}
    if href.startswith("/") or href.startswith("?"):
        return {"kind": "internal", "path": href}
    try:
        u = urlparse(urljoin(source_origin, href))
        full = f"{u.scheme}://{u.netloc}"
        if full == source_origin:
            path = u.path + (("?" + u.query) if u.query else "") + (("#" + u.fragment) if u.fragment else "")
            return {"kind": "internal", "path": path}
        if any(u.netloc.endswith(h) for h in ANALYTICS_HOSTS):
            return {"kind": "analytics", "host": u.netloc, "value": href}
        return {"kind": "external", "host": u.netloc, "value": href}
    except Exception:
        return {"kind": "unknown", "value": href}


def extract_interactive(html: str, source_origin: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    links: list[dict] = []
    for a in soup.find_all("a", href=True):
        text = (a.get_text(strip=True) or "")[:120]
        href = a.get("href") or ""
        aria = a.get("aria-label") or ""
        title = a.get("title") or ""
        target = a.get("target") or "_self"
        cls = " ".join(a.get("class") or [])
        looks_button = bool(re.search(r"\bbtn\b|\bbutton\b", cls, re.I))
        dest = classify_href(href, source_origin)
        img = a.find("img")
        links.append({
            "text": text or aria or title or "(no text)",
            "href": href,
            "destination": dest,
            "target": target,
            "role": "button-link" if looks_button else "link",
            "hasImageOnly": (not text) and img is not None,
            "imageAlt": (img.get("alt") or "") if (not text and img is not None) else None,
        })

    buttons: list[dict] = []
    seen_buttons: set[int] = set()
    candidates = soup.find_all(["button"]) + soup.select('[role="button"]')
    for b in candidates:
        if id(b) in seen_buttons:
            continue  # dedupe — a <button role="tab"> hits both selectors
        seen_buttons.add(id(b))
        if b.name == "a":
            continue  # already counted as a link
        # Skip role-tab elements: they're inventoried in the `tabs` list
        if (b.get("role") or "").lower() == "tab":
            continue
        text = (b.get_text(strip=True) or "")[:120]
        aria = b.get("aria-label") or ""
        btype = b.get("type") or "button"
        onclick = b.get("onclick") or ""
        form_action = b.get("formaction") or ""
        aria_controls = b.get("aria-controls") or ""
        aria_expanded = b.get("aria-expanded")
        cls = " ".join(b.get("class") or [])
        inferred = "unknown"
        if btype == "submit":
            inferred = "submit-form"
        elif aria_expanded is not None:
            inferred = f"toggle-expanded (controls={aria_controls or '?'})"
        elif re.search(r"menu-toggle|hamburger", cls, re.I):
            inferred = "open-mobile-menu"
        elif re.search(r"close|dismiss", cls + " " + aria, re.I):
            inferred = "close-modal-or-banner"
        elif re.search(r"accept|agree|ok|got.?it", text + " " + cls, re.I):
            inferred = "cookie-banner-accept"
        elif onclick:
            inferred = f"inline-handler: {onclick[:80]}"
        buttons.append({
            "text": text or aria or "(no text)",
            "type": btype,
            "inferredBehavior": inferred,
            "ariaControls": aria_controls,
            "formAction": form_action,
        })

    forms: list[dict] = []
    for f in soup.find_all("form"):
        action = f.get("action") or ""
        method = (f.get("method") or "GET").upper()
        fields = []
        for inp in f.find_all(["input", "textarea", "select"]):
            name = inp.get("name")
            if not name:
                continue
            ftype = inp.get("type") or inp.name or "text"
            # Skip hidden inputs unless their name suggests user data — we
            # never want to surface CSRF or session tokens in the map.
            if ftype == "hidden" and not re.search(r"email|name|phone|message|subject", name, re.I):
                continue
            fields.append({
                "name": name,
                "type": ftype,
                "required": inp.get("required") is not None,
                "label": (inp.get("placeholder") or inp.get("aria-label") or "")[:200],
            })
        forms.append({
            "action": action,
            "method": method,
            "action_destination": classify_href(action, source_origin),
            "fields": fields,
        })

    iframes: list[dict] = []
    for i in soup.find_all("iframe"):
        src = i.get("src") or ""
        if not src:
            continue
        dest = classify_href(src, source_origin)
        if re.search(r"google\.com/maps", src):
            purpose = "google-map"
        elif re.search(r"youtube\.com/embed|player\.vimeo\.com", src):
            purpose = "video-embed"
        elif re.search(r"autoops\.com/chat", src):
            purpose = "chat-widget"
        elif re.search(r"autoops\.com", src):
            purpose = "booking-widget"
        elif re.search(r"facebook\.com|twitter\.com/widgets", src):
            purpose = "social-embed"
        elif re.search(r"stripe\.com|js\.stripe", src):
            purpose = "payment-iframe"
        elif re.search(r"intercom\.com|crisp\.chat|tawk\.to|drift\.com", src):
            purpose = "chat-widget"
        else:
            purpose = "unknown"
        iframes.append({
            "src": src,
            "title": i.get("title") or "",
            "purpose": purpose,
            "destination": dest,
        })

    accordions: list[dict] = []
    for d in soup.find_all("details"):
        s = d.find("summary")
        accordions.append({
            "type": "details",
            "summary": (s.get_text(strip=True) if s else "")[:200],
            "open": d.has_attr("open"),
        })
    for h in soup.select(
        '[class*="accordion"] [class*="header"], [class*="faq"] [class*="question"]'
    ):
        text = (h.get_text(strip=True) or "")[:200]
        if text:
            accordions.append({"type": "accordion-class", "summary": text})

    tabs: list[dict] = []
    for t in soup.select('[role="tab"], [role="tablist"] > *'):
        tabs.append({
            "label": (t.get_text(strip=True) or "")[:80],
            "controls": t.get("aria-controls") or "",
            "selected": t.get("aria-selected") == "true",
        })

    return {
        "links": links,
        "buttons": buttons,
        "forms": forms,
        "iframes": iframes,
        "accordions": accordions,
        "tabs": tabs,
    }


def build(out_dir: Path, source_url: str | None = None) -> dict:
    routes_data: list[dict] = []
    pages_dir = out_dir / "raw" / "pages"
    if not pages_dir.exists():
        raise FileNotFoundError(f"No pages dir at {pages_dir}")

    if source_url is None:
        # Try preflight.json
        pf = out_dir / "preflight.json"
        if pf.exists():
            try:
                source_url = json.loads(pf.read_text(encoding="utf-8")).get("base_origin")
            except Exception:
                pass
    source_origin = source_url or "https://example.com"
    parsed = urlparse(source_origin)
    source_origin = f"{parsed.scheme}://{parsed.netloc}"

    aggregate = {
        "total_links": 0,
        "total_buttons": 0,
        "total_forms": 0,
        "total_iframes": 0,
        "total_accordions": 0,
        "total_tabs": 0,
        "external_destinations": set(),
        "analytics_destinations": set(),
        "same_origin_form_actions": set(),
        "cross_origin_form_actions": set(),
        "iframe_purposes": {},
    }

    for page_dir in sorted(pages_dir.iterdir()):
        if not page_dir.is_dir():
            continue
        slug = page_dir.name
        rendered = page_dir / "rendered.html"
        if not rendered.exists():
            continue
        html = rendered.read_text(encoding="utf-8", errors="ignore")
        meta_path = page_dir / "meta.json"
        meta = {}
        if meta_path.exists():
            try: meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception: pass
        url_file = page_dir / "url.txt"
        url = url_file.read_text(encoding="utf-8").strip() if url_file.exists() else meta.get("url", "")
        ix = extract_interactive(html, source_origin)

        routes_data.append({
            "url": url,
            "slug": slug,
            "title": meta.get("title", ""),
            **ix,
        })

        aggregate["total_links"] += len(ix["links"])
        aggregate["total_buttons"] += len(ix["buttons"])
        aggregate["total_forms"] += len(ix["forms"])
        aggregate["total_iframes"] += len(ix["iframes"])
        aggregate["total_accordions"] += len(ix["accordions"])
        aggregate["total_tabs"] += len(ix["tabs"])
        for link in ix["links"]:
            k = link["destination"]["kind"]
            if k == "external":
                aggregate["external_destinations"].add(link["destination"]["host"])
            elif k == "analytics":
                aggregate["analytics_destinations"].add(link["destination"]["host"])
        for f in ix["forms"]:
            k = f["action_destination"]["kind"]
            if k == "internal":
                aggregate["same_origin_form_actions"].add(f["action"] or "(empty)")
            elif k == "external":
                aggregate["cross_origin_form_actions"].add(f["action"])
        for i in ix["iframes"]:
            aggregate["iframe_purposes"][i["purpose"]] = aggregate["iframe_purposes"].get(i["purpose"], 0) + 1

    # Convert sets for JSON
    aggregate["external_destinations"] = sorted(aggregate["external_destinations"])
    aggregate["analytics_destinations"] = sorted(aggregate["analytics_destinations"])
    aggregate["same_origin_form_actions"] = sorted(aggregate["same_origin_form_actions"])
    aggregate["cross_origin_form_actions"] = sorted(aggregate["cross_origin_form_actions"])

    return {
        "metadata": {
            "source_url": source_origin,
            "generated_at": datetime.utcnow().isoformat(),
            "agent": "dna-website/interactive_map v0.2",
            "route_count": len(routes_data),
        },
        "routes": routes_data,
        "aggregate": aggregate,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--source-url")
    args = ap.parse_args()
    out_dir = Path(args.out).resolve()
    result = build(out_dir, source_url=args.source_url)
    analysis_dir = out_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    path = analysis_dir / "interactive-map.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    agg = result["aggregate"]
    print(f"interactive-map: {len(result['routes'])} routes, "
          f"{agg['total_links']} links, {agg['total_buttons']} buttons, "
          f"{agg['total_forms']} forms, {agg['total_iframes']} iframes, "
          f"{agg['total_accordions']} accordions, {agg['total_tabs']} tabs "
          f"-> {path}")


if __name__ == "__main__":
    main()
