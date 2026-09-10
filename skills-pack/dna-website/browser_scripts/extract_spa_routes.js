/**
 * SPA route sniffer.
 *
 * Hooks into client-side routing so we can discover routes that don't
 * appear as <a href> links — pushed via history.pushState, popped via
 * popstate, or embedded in framework data (Next.js, Nuxt, etc).
 *
 * Stores discovered URLs at window.__DNA_SPA_ROUTES which the crawler
 * reads back via page.evaluate().
 *
 * Should be injected via page.add_init_script BEFORE navigation so the
 * hooks are in place when the SPA's first render runs.
 */
(() => {
  if (window.__DNA_SPA_ROUTES) return;
  const routes = new Set();
  window.__DNA_SPA_ROUTES = [];

  function record(url) {
    if (!url) return;
    try {
      const abs = new URL(url, window.location.href).toString();
      if (!routes.has(abs)) {
        routes.add(abs);
        window.__DNA_SPA_ROUTES.push(abs);
      }
    } catch {}
  }

  // 1. Hook history API
  const origPush = history.pushState;
  const origReplace = history.replaceState;
  history.pushState = function (state, title, url) {
    record(url);
    return origPush.apply(this, arguments);
  };
  history.replaceState = function (state, title, url) {
    record(url);
    return origReplace.apply(this, arguments);
  };
  window.addEventListener('popstate', () => record(window.location.href));

  // 2. Scan framework artifacts after first paint
  setTimeout(() => {
    // Next.js
    try {
      const nd = window.__NEXT_DATA__;
      if (nd) {
        if (nd.page) record(nd.page);
        if (nd.props?.pageProps?.routes) {
          for (const r of nd.props.pageProps.routes) record(r.path || r.url || r);
        }
      }
    } catch {}

    // Nuxt
    try {
      if (window.__NUXT__?.routePath) record(window.__NUXT__.routePath);
      if (window.__NUXT__?.config?.routes) {
        for (const r of window.__NUXT__.config.routes) record(r);
      }
    } catch {}

    // Generic data-route attributes
    for (const el of document.querySelectorAll('[data-route], [data-href], [data-url]')) {
      record(el.dataset.route || el.dataset.href || el.dataset.url);
    }

    // <link rel="prefetch" as="document">
    for (const link of document.querySelectorAll('link[rel="prefetch"][as="document"]')) {
      record(link.href);
    }
  }, 1000);
})();
