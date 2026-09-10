/**
 * Custom network-idle detector.
 *
 * Returns a promise that resolves when there has been no fetch/xhr activity
 * for the given idle window (default 500ms), or rejects after a hard timeout.
 *
 * Playwright's built-in 'networkidle' state is sometimes too strict (waits
 * for long-poll or websocket activity to stop) or too lax (resolves before
 * the SPA finishes hydrating). This is the middle path.
 *
 * Usage from Playwright:
 *   await page.evaluate(IDLE_SCRIPT, { idleMs: 800, timeoutMs: 15000 });
 */
({ idleMs = 500, timeoutMs = 15000 } = {}) => {
  return new Promise((resolve, reject) => {
    let inflight = 0;
    let timer = null;
    const start = Date.now();

    const check = () => {
      if (inflight === 0) {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => resolve('idle'), idleMs);
      } else if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    };

    const origFetch = window.fetch;
    window.fetch = function (...args) {
      inflight++;
      check();
      return origFetch.apply(this, args).finally(() => {
        inflight--;
        check();
      });
    };

    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (...args) {
      this.__dnaTracked = true;
      return origOpen.apply(this, args);
    };
    XMLHttpRequest.prototype.send = function (...args) {
      if (this.__dnaTracked) {
        inflight++;
        check();
        this.addEventListener('loadend', () => {
          inflight--;
          check();
        });
      }
      return origSend.apply(this, args);
    };

    setTimeout(() => reject(new Error('idle-timeout')), timeoutMs);
    check();
  });
}
