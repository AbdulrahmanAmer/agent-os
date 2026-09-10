/**
 * Injected into every captured page. Walks the DOM and dumps computed
 * styles for every element. Output shape matches ElementStyles in
 * scripts/models.py.
 *
 * This is the canonical list of styles we capture — extend here, not in the
 * Python side, since the browser is the only place that can resolve computed
 * values.
 */
(() => {
  const STYLE_PROPS = [
    'color', 'background-color', 'background-image',
    'font-family', 'font-size', 'font-weight', 'line-height', 'letter-spacing',
    'padding', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
    'margin', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left',
    'border-radius', 'box-shadow', 'border',
    'border-color', 'border-width', 'border-style',
    'outline-color', 'outline-width', 'outline-style',
    'display', 'position',
    'flex-direction', 'gap', 'align-items', 'justify-content',
    'grid-template-columns', 'grid-template-rows',
    'transition', 'transform', 'animation',
    'opacity', 'z-index',
    'fill', 'stroke',
  ];

  const MAX_ELEMENTS = 5000;   // upper bound to prevent runaway pages
  const out = [];

  function cssPath(el) {
    const parts = [];
    let cur = el;
    for (let i = 0; i < 6 && cur && cur.tagName; i++) {
      const parent = cur.parentElement;
      if (!parent) break;
      const sibs = [...parent.children].filter((c) => c.tagName === cur.tagName);
      const idx = sibs.indexOf(cur);
      parts.unshift(`${cur.tagName.toLowerCase()}:nth(${idx})`);
      cur = parent;
    }
    return parts.join('>');
  }

  function walk(el) {
    if (out.length >= MAX_ELEMENTS) return;
    if (!(el instanceof Element)) return;

    const cs = window.getComputedStyle(el);
    const styles = {};
    for (const prop of STYLE_PROPS) {
      const v = cs.getPropertyValue(prop);
      if (v) styles[prop] = v.trim();
    }

    const text = (el.children.length === 0 && el.textContent)
      ? el.textContent.trim().slice(0, 200)
      : null;

    const rect = el.getBoundingClientRect();
    out.push({
      tag: el.tagName.toLowerCase(),
      classes: el.className && typeof el.className === 'string'
        ? el.className.split(/\s+/).filter(Boolean)
        : [],
      id: el.id || null,
      role: el.getAttribute('role') || null,
      path: cssPath(el),
      text,
      styles,
      bbox: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
    });

    for (const child of el.children) walk(child);
  }

  walk(document.body);
  return out;
})();
