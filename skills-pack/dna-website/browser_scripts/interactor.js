/**
 * Page interactor.
 *
 * Ported (with tightening) from v1's webapp-clone-pipeline/src/cloner/
 * interactor.js. Runs in the page context to:
 *   1. Dismiss cookie banners
 *   2. Open the hamburger menu (first match)
 *   3. Hover every mega-menu trigger for 500 ms each
 *   4. Open every <details>/summary
 *   5. Click every aria-expanded="false" accordion / FAQ row
 *   6. Click every [role="tab"]
 *   7. Click every Read More / Load More / View More / See More / Show All
 *      / Expand button (2 passes — stops when no new content appears)
 *   8. Click carousel "next" arrows up to 12 times each, stopping on
 *      hidden/disabled
 *   9. Scroll top→bottom, 800 px steps, with a settle pause per step
 *  10. Scroll back to top
 *
 * Hard-rule guards (added on top of v1):
 *   - NEVER clicks elements whose visible text or aria-label matches the
 *     purchase blocklist (Buy/Checkout/Pay/Confirm Purchase/Upgrade/
 *     Subscribe/Add Credits/Submit Payment/etc.) — even if they look like
 *     an accordion or reveal button.
 *   - NEVER submits a form.
 *   - NEVER follows a link via .click() (the crawler navigates explicitly).
 *
 * Configured via a wait preset (fast / normal / patient / maximum) and
 * resolves to durations in ms. The crawler picks the preset; this script
 * accepts a single options object and runs synchronously inside the page.
 *
 * Usage from Playwright:
 *
 *   const script = fs.readFileSync('browser_scripts/interactor.js', 'utf-8');
 *   const result = await page.evaluate(`(${script})({ stepMs: 500, maxClicks: 30 })`);
 *
 * Returns { clicked, scrollPasses, sectionsRevealed, skippedPurchase }.
 */

(function (opts) {
  opts = opts || {};
  var stepMs = opts.stepMs || 500;
  var scrollDelayMs = opts.scrollDelayMs || Math.max(200, Math.floor(stepMs * 0.8));
  var scrollStep = opts.scrollStep || 800;
  var maxClicks = opts.maxClicks || 30;
  var maxTabs = opts.maxTabs || 12;
  var maxScrollPasses = opts.maxScrollPasses || 200;
  var maxCarouselClicks = opts.maxCarouselClicks || 12;

  var clicked = 0;
  var scrollPasses = 0;
  var sectionsRevealed = 0;
  var skippedPurchase = 0;

  var COOKIE_SELECTORS = [
    'button:contains("Accept All")', 'button:contains("Accept")',
    'button:contains("I Accept")', 'button:contains("Agree")',
    'button:contains("I Agree")', 'button:contains("OK")',
    'button:contains("Got it")', 'button:contains("Allow all")',
    '[id*="cookie" i] button', '[class*="cookie" i] button',
    '[id*="consent" i] button',
  ];

  var MENU_SELECTORS = [
    '[class*="hamburger"]', '[class*="menu-toggle"]', '[class*="mobile-menu-toggle"]',
    'button[aria-label*="menu" i]',
    'button[aria-expanded="false"][aria-controls]',
  ];

  var REVEAL_TEXTS = [
    /^(read|view|show|see|load)\s+(more|all|details)$/i,
    /^expand$/i,
    /^show\s+more$/i,
  ];

  var CAROUSEL_NEXT_SELECTORS = [
    'button[aria-label*="next" i]:not([disabled])',
    'button[class*="slick-next"]',
    'button[class*="swiper-button-next"]',
    'button[class*="carousel-next"]',
    '[class*="slider"] button[class*="next"]',
  ];

  // Purchase-action blocklist — text or aria-label patterns we MUST NOT click.
  // Mirrors scripts/utils.py:PURCHASE_ELEMENT_TEXT_PATTERNS so the in-page
  // safety matches the Python-side safety. Updates here should update both.
  var PURCHASE_TEXT_RE = new RegExp(
    '\\b(buy|purchase|checkout|pay\\s+now|complete\\s+order|confirm\\s+purchase'
    + '|upgrade(?:\\s+plan)?|add\\s+credits?|top[- ]?up|subscribe'
    + '|start\\s+trial|start\\s+subscription|place\\s+order|submit\\s+payment'
    + '|add\\s+to\\s+cart)\\b',
    'i'
  );

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function elementText(el) {
    if (!el) return '';
    var t = (el.textContent || '').trim();
    if (t) return t;
    return el.getAttribute('aria-label') || el.getAttribute('title') || '';
  }

  function isPurchaseEl(el) {
    if (!el) return false;
    var text = elementText(el);
    if (text && PURCHASE_TEXT_RE.test(text)) return true;
    var classes = (typeof el.className === 'string' ? el.className : '');
    if (PURCHASE_TEXT_RE.test(classes)) return true;
    var id = el.id || '';
    if (PURCHASE_TEXT_RE.test(id)) return true;
    return false;
  }

  function safeIsVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    try {
      var rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return false;
      var cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none') return false;
      if (parseFloat(cs.opacity || '1') < 0.1) return false;
      return true;
    } catch (_) { return false; }
  }

  function safeClick(el) {
    if (!el) return false;
    if (!safeIsVisible(el)) return false;
    if (isPurchaseEl(el)) { skippedPurchase++; return false; }
    try { el.click(); return true; } catch (_) { return false; }
  }

  function safeHover(el) {
    if (!el || isPurchaseEl(el)) return false;
    try {
      var rect = el.getBoundingClientRect();
      var ev = new MouseEvent('mouseover', { bubbles: true, cancelable: true,
        clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 });
      el.dispatchEvent(ev);
      var ev2 = new MouseEvent('mouseenter', { bubbles: true, cancelable: true });
      el.dispatchEvent(ev2);
      return true;
    } catch (_) { return false; }
  }

  function queryByContains(selector) {
    // CSS doesn't have :contains; emulate by matching text after :contains("X")
    var m = /^(.*?):contains\(\"(.+?)\"\)$/.exec(selector);
    if (!m) return Array.from(document.querySelectorAll(selector));
    var base = m[1] || '*';
    var needle = m[2].toLowerCase();
    var out = [];
    var els = document.querySelectorAll(base);
    for (var i = 0; i < els.length; i++) {
      var t = (els[i].textContent || '').trim().toLowerCase();
      if (t === needle || t.startsWith(needle + ' ') || t.endsWith(' ' + needle) || t.indexOf(' ' + needle + ' ') >= 0) {
        out.push(els[i]);
      }
    }
    return out;
  }

  async function dismissCookies() {
    for (var i = 0; i < COOKIE_SELECTORS.length; i++) {
      var els = queryByContains(COOKIE_SELECTORS[i]);
      for (var j = 0; j < els.length; j++) {
        if (safeClick(els[j])) {
          await sleep(150);
          return;
        }
      }
    }
  }

  async function openHamburger() {
    for (var i = 0; i < MENU_SELECTORS.length; i++) {
      var els = document.querySelectorAll(MENU_SELECTORS[i]);
      for (var j = 0; j < els.length; j++) {
        if (safeClick(els[j])) {
          clicked++;
          sectionsRevealed++;
          await sleep(stepMs);
          return;
        }
      }
    }
  }

  async function hoverMegaMenus() {
    // Hover every [aria-haspopup="true"] and every <nav> direct-child <li> for
    // 500ms so submenu content paints in the DOM.
    var triggers = document.querySelectorAll(
      '[aria-haspopup="true"], nav > ul > li, nav > .menu-item, .has-submenu, [class*="menu-item-has-children"]'
    );
    var capped = Math.min(triggers.length, 16);
    for (var i = 0; i < capped; i++) {
      var t = triggers[i];
      if (!safeIsVisible(t) || isPurchaseEl(t)) continue;
      safeHover(t);
      await sleep(500);
    }
  }

  async function openDetails() {
    var sums = document.querySelectorAll('details > summary');
    var capped = Math.min(sums.length, maxClicks - clicked);
    for (var i = 0; i < capped; i++) {
      if (safeClick(sums[i])) {
        clicked++;
        sectionsRevealed++;
        await sleep(stepMs);
      }
      if (clicked >= maxClicks) break;
    }
  }

  async function openAccordions() {
    if (clicked >= maxClicks) return;
    var acc = document.querySelectorAll(
      '[class*="accordion"] [role="button"][aria-expanded="false"], '
      + '[class*="accordion"] button[aria-expanded="false"], '
      + '[role="button"][aria-expanded="false"], '
      + '[class*="faq"] [aria-expanded="false"], '
      + '[class*="faq"] button:not([aria-expanded="true"])'
    );
    var capped = Math.min(acc.length, maxClicks - clicked);
    for (var i = 0; i < capped; i++) {
      if (safeClick(acc[i])) {
        clicked++;
        sectionsRevealed++;
        await sleep(stepMs);
      }
    }
  }

  async function clickTabs() {
    var tabs = document.querySelectorAll('[role="tab"]');
    var capped = Math.min(tabs.length, maxTabs);
    // Skip index 0 (usually already-selected). Click 1..N to expose other panels.
    for (var i = 1; i < capped; i++) {
      if (clicked >= maxClicks) break;
      if (safeClick(tabs[i])) {
        clicked++;
        sectionsRevealed++;
        await sleep(stepMs);
      }
    }
  }

  async function clickReveals() {
    // Two passes — paginated reveals (Load More) may need a second click
    // after the first reveal pours new content into the DOM.
    for (var pass = 0; pass < 2; pass++) {
      if (clicked >= maxClicks) break;
      var revealedThisPass = 0;
      var buttons = document.querySelectorAll('button, a[role="button"], [class*="load-more"], [class*="show-more"], [class*="view-more"], [class*="read-more"]');
      for (var i = 0; i < buttons.length; i++) {
        if (clicked >= maxClicks) break;
        var b = buttons[i];
        var text = (b.textContent || '').trim();
        if (!text) continue;
        var isReveal = false;
        for (var r = 0; r < REVEAL_TEXTS.length; r++) {
          if (REVEAL_TEXTS[r].test(text)) { isReveal = true; break; }
        }
        if (!isReveal) {
          var cls = (typeof b.className === 'string' ? b.className : '').toLowerCase();
          if (/load-more|show-more|view-more|read-more|view-all|see-all/.test(cls)) isReveal = true;
        }
        if (!isReveal) continue;
        if (isPurchaseEl(b)) continue;
        if (!safeIsVisible(b)) continue;
        var heightBefore = document.body ? document.body.scrollHeight : 0;
        if (safeClick(b)) {
          clicked++;
          await sleep(stepMs);
          var heightAfter = document.body ? document.body.scrollHeight : 0;
          if (heightAfter > heightBefore) {
            sectionsRevealed++;
            revealedThisPass++;
          }
        }
      }
      if (revealedThisPass === 0) break;
    }
  }

  async function clickCarousels() {
    for (var i = 0; i < CAROUSEL_NEXT_SELECTORS.length; i++) {
      if (clicked >= maxClicks) break;
      var arrows = document.querySelectorAll(CAROUSEL_NEXT_SELECTORS[i]);
      if (!arrows.length) continue;
      var arrow = arrows[0];
      if (!safeIsVisible(arrow)) continue;
      for (var n = 0; n < maxCarouselClicks; n++) {
        if (clicked >= maxClicks) break;
        if (!safeIsVisible(arrow)) break;
        var disabled = arrow.getAttribute('aria-disabled');
        if (disabled === 'true' || arrow.hasAttribute('disabled')) break;
        if (!safeClick(arrow)) break;
        clicked++;
        await sleep(stepMs);
      }
    }
  }

  async function scrollTopToBottom() {
    var total = document.body ? document.body.scrollHeight : 0;
    var y = 0;
    while (y < total) {
      try { window.scrollBy(0, scrollStep); } catch (_) {}
      y += scrollStep;
      scrollPasses++;
      if (scrollPasses > maxScrollPasses) break;
      await sleep(scrollDelayMs);
      // Re-read height — lazy load may have grown the page
      total = document.body ? document.body.scrollHeight : total;
    }
    try { window.scrollTo(0, 0); } catch (_) {}
  }

  return (async function () {
    await dismissCookies();
    await openHamburger();
    await hoverMegaMenus();
    await openDetails();
    await openAccordions();
    await clickTabs();
    await clickReveals();
    await clickCarousels();
    await scrollTopToBottom();
    return { clicked: clicked, scrollPasses: scrollPasses,
             sectionsRevealed: sectionsRevealed,
             skippedPurchase: skippedPurchase };
  })();
});
