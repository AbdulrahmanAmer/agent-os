"""
AI-powered interaction wiring: produces a single shared runtime.js +
optional css that recreates the captured site's interactive patterns
in vanilla JS.

Inputs from the orchestrator:
  - The full interactive-map.json (every route's links/buttons/forms/
    iframes/accordions/tabs)
  - The list of slugs for cross-page navigation

Outputs written to real-project/assets/js/runtime.js and
real-project/assets/css/runtime.css (only if the AI emits CSS).

Hard safety:
  - The prompt explicitly bans purchase-button wiring and form auto-
    submission. We also run a static check on the returned JS and
    reject it if it contains `.submit()`, `fetch(`...payment patterns,
    or window.location assignments to URLs matching the purchase
    blocklist.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .llm import LLMClient
from .prompts import WIRE_INTERACTIONS_INSTRUCTIONS

log = logging.getLogger(__name__)


# Static post-checks on the AI's JS output
FORBIDDEN_JS_PATTERNS = [
    re.compile(r"\.submit\s*\("),
    re.compile(r"fetch\s*\([^)]*['\"]/?(?:buy|checkout|purchase|pay|charge|subscribe|upgrade|order|confirm)", re.I),
    re.compile(r"window\.location\s*[=.][^=][^;]*['\"](?:[^'\"]*?)/(?:buy|checkout|purchase|pay|charge|subscribe|upgrade|confirm-purchase)", re.I),
    re.compile(r"navigator\.sendBeacon"),
    re.compile(r"document\.cookie\s*="),
]


@dataclass
class WireStats:
    js_bytes: int = 0
    css_bytes: int = 0
    patterns_wired: list[str] = field(default_factory=list)
    patterns_skipped: list[str] = field(default_factory=list)
    forbidden_patterns_found: list[str] = field(default_factory=list)
    accepted: bool = False
    notes: list[str] = field(default_factory=list)


def _build_prompt(interactive_map: dict, slugs: list[str]) -> str:
    aggregate = interactive_map.get("aggregate") or {}
    iframe_purposes = aggregate.get("iframe_purposes") or {}
    # Sample the first 3 routes for concrete examples
    sample_routes = (interactive_map.get("routes") or [])[:3]
    sample = [{
        "slug": r.get("slug"),
        "buttons": (r.get("buttons") or [])[:10],
        "forms": r.get("forms") or [],
        "iframes": r.get("iframes") or [],
        "accordions": (r.get("accordions") or [])[:5],
        "tabs": (r.get("tabs") or [])[:5],
    } for r in sample_routes]
    return f"""\
{WIRE_INTERACTIONS_INSTRUCTIONS}

--- BEGIN INPUTS ---

site-wide pages (slugs):
{json.dumps(slugs, indent=2)}

site-wide aggregate (interactive-map):
{json.dumps(aggregate, indent=2)}

iframe purposes summary:
{json.dumps(iframe_purposes, indent=2)}

sample route detail (first 3 routes):
{json.dumps(sample, indent=2)[:8000]}

--- END INPUTS ---

Return ONLY the JSON object — no fence, no preamble.
"""


def _static_check_js(js: str) -> list[str]:
    """Return a list of forbidden patterns found in the JS output."""
    findings = []
    for pat in FORBIDDEN_JS_PATTERNS:
        m = pat.search(js)
        if m:
            findings.append(m.group(0)[:80])
    return findings


def run(
    interactive_map: dict,
    slugs: list[str],
    real_project_dir: Path,
    llm: LLMClient,
) -> WireStats:
    stats = WireStats()
    prompt = _build_prompt(interactive_map, slugs)

    try:
        reply = llm.ask(prompt, expect_json=True)
    except Exception as e:
        log.error(f"interaction wiring LLM call failed: {e}")
        stats.notes.append(f"LLM failed: {e}; using deterministic fallback")
        reply = _fallback_runtime()

    js = reply.get("js") or ""
    css = reply.get("css") or ""
    patterns = reply.get("patterns_wired") or []
    skipped = reply.get("patterns_skipped_by_policy") or []

    # Empty JS → fall back to the deterministic runtime (mock mode triggers this)
    if not js.strip():
        log.info("LLM returned no JS; using deterministic fallback runtime")
        reply = _fallback_runtime()
        js = reply["js"]; css = reply["css"]
        patterns = reply["patterns_wired"]; skipped = reply["patterns_skipped_by_policy"]
        stats.notes.append("deterministic fallback runtime used")

    findings = _static_check_js(js)
    if findings:
        log.warning(f"runtime.js contained forbidden patterns: {findings}; rejecting and using fallback")
        stats.forbidden_patterns_found = findings
        reply = _fallback_runtime()
        js = reply["js"]; css = reply["css"]; patterns = reply["patterns_wired"]; skipped = reply["patterns_skipped_by_policy"]

    js_dir = real_project_dir / "assets" / "js"
    js_dir.mkdir(parents=True, exist_ok=True)
    (js_dir / "runtime.js").write_text(js, encoding="utf-8")
    stats.js_bytes = len(js)
    stats.accepted = True

    if css.strip():
        css_dir = real_project_dir / "assets" / "css"
        css_dir.mkdir(parents=True, exist_ok=True)
        (css_dir / "runtime.css").write_text(css, encoding="utf-8")
        stats.css_bytes = len(css)

    stats.patterns_wired = patterns
    stats.patterns_skipped = skipped
    stats.notes.extend(reply.get("notes") or [])
    return stats


def _fallback_runtime() -> dict:
    """Deterministic minimal runtime — used when the LLM is unavailable
    or its output fails the safety check. Covers the most common patterns
    without any AI."""
    js = r"""
/* runtime.js — dna-website normalizer deterministic fallback
 * Wires: menu toggle, accordion focus, modal trigger, sticky-on-scroll,
 *        cookie banner dismiss, form preventDefault, purchase-button warn.
 * No external deps. Loaded with <script defer>.
 */
(function () {
  'use strict';
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  // 1. Menu toggle (hamburger / mobile nav)
  $$('[data-menu-toggle], .menu-toggle, [aria-controls][aria-expanded]').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      var expanded = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!expanded));
      var controls = btn.getAttribute('aria-controls');
      var target = controls ? document.getElementById(controls) : btn.nextElementSibling;
      if (target) target.classList.toggle('is-open');
      document.body.classList.toggle('menu-open');
    });
  });

  // 2. Modal triggers
  $$('[data-modal]').forEach(function (trigger) {
    trigger.addEventListener('click', function (e) {
      e.preventDefault();
      var id = trigger.getAttribute('data-modal');
      var dlg = document.getElementById(id);
      if (dlg && typeof dlg.showModal === 'function') dlg.showModal();
      else if (dlg) dlg.classList.add('is-open');
    });
  });
  $$('[data-modal-close]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var dlg = btn.closest('dialog');
      if (dlg && typeof dlg.close === 'function') dlg.close();
      else if (dlg) dlg.classList.remove('is-open');
    });
  });

  // 3. Sticky header on scroll
  var header = $('header');
  if (header) {
    var onScroll = function () {
      header.classList.toggle('is-scrolled', window.scrollY > 8);
    };
    document.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  // 4. Cookie banner dismiss
  $$('.cookie-banner [data-dismiss], [data-cookie-dismiss]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var banner = btn.closest('.cookie-banner') || btn.closest('[data-cookie-banner]');
      if (banner) banner.style.display = 'none';
      try { localStorage.setItem('cookie-banner-dismissed', '1'); } catch (_) {}
    });
  });

  // 5. Forms: never submit. Warn the operator.
  $$('form[data-original-action], form').forEach(function (form) {
    if (form.dataset.allowSubmit === 'true') return;
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var orig = form.getAttribute('data-original-action') || form.getAttribute('action') || '';
      console.warn('[dna-website] form submission blocked (original action: ' + orig + ')');
      var alertEl = form.querySelector('[data-form-notice]') || document.createElement('p');
      if (!form.contains(alertEl)) {
        alertEl.setAttribute('data-form-notice', '');
        alertEl.textContent = 'This form is a static clone — submissions are disabled until wired up.';
        form.appendChild(alertEl);
      }
    });
  });

  // 6. Purchase-action buttons — warn rather than execute
  $$('[data-todo="needs-operator-wiring"]').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      console.warn('[dna-website] purchase-action button "%s" requires manual wiring', btn.textContent.trim());
    });
  });

  // 7. Smooth-scroll for in-page anchor links
  $$('a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var id = a.getAttribute('href').slice(1);
      if (!id) return;
      var target = document.getElementById(id);
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });
})();
"""
    css = r"""
/* runtime.css — fallback styling for runtime patterns */
.is-open { display: block !important; }
body.menu-open { overflow: hidden; }
header.is-scrolled {
  background: var(--color-header-bg, #fff);
  box-shadow: var(--shadow-sm, 0 4px 8px rgba(0,0,0,.06));
}
[data-form-notice] {
  margin-top: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: #fff5e6;
  border-left: 3px solid var(--color-accent-warning, #f96138);
  color: #6b3a17;
  font-size: 0.875rem;
}
"""
    return {
        "js": js.strip() + "\n",
        "css": css.strip() + "\n",
        "patterns_wired": [
            "menu-toggle", "modal-triggers", "sticky-header",
            "cookie-banner-dismiss", "form-prevent-submit",
            "purchase-button-warn", "smooth-scroll-anchors",
        ],
        "patterns_skipped_by_policy": [
            "form-auto-submit",
            "purchase-button-handlers",
            "credit-card-tokenization",
        ],
        "notes": ["deterministic fallback runtime"],
    }
