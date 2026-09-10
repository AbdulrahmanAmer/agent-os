/**
 * Scroll-to-bottom-and-wait loop. Used to materialize lazy-loaded content.
 *
 * Scrolls in increments of 80% of the viewport height, waits ~500ms between
 * scrolls, and stops when the document height stops growing OR a hard cap
 * of 30 seconds is reached.
 *
 * Returns the final scroll height (useful for logging).
 */
(async () => {
  const HARD_CAP_MS = 30000;
  const STEP_PAUSE_MS = 500;
  const NO_GROWTH_THRESHOLD = 3;   // 3 consecutive non-growing steps = done

  const started = Date.now();
  let lastHeight = document.body.scrollHeight;
  let noGrowthCount = 0;

  while (Date.now() - started < HARD_CAP_MS) {
    window.scrollBy(0, window.innerHeight * 0.8);
    await new Promise((r) => setTimeout(r, STEP_PAUSE_MS));

    const newHeight = document.body.scrollHeight;
    if (newHeight === lastHeight) {
      noGrowthCount++;
      if (noGrowthCount >= NO_GROWTH_THRESHOLD) break;
    } else {
      noGrowthCount = 0;
      lastHeight = newHeight;
    }

    // Also bail if we've reached the actual bottom
    if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 2) {
      noGrowthCount++;
    }
  }

  // Scroll back to top so the screenshot starts from the head
  window.scrollTo(0, 0);
  return lastHeight;
})();
