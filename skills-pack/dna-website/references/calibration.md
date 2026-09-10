# Calibration

> How to tune the tuning constants in `scripts/analyze_dna.py` against real-world sites without overfitting to one or two.

---

## Why calibration matters

The DNA-extraction algorithms have ~12 tuning constants spread across color clustering, typography scale detection, spacing inference, shadow merging, and component pattern matching. The defaults in `scripts/analyze_dna.py` were chosen from first principles, not from data. Real sites are messier than the assumptions; the constants need to be retuned periodically.

Calibration is the discipline of: run the analyzer against a fixed set of well-understood sites, compare the output to what a human reviewer says is right, adjust the constants, re-run, compare again.

---

## The calibration corpus

Pick five sites that exhibit different design-system structures. Document each one's "ground truth" in this file. The current corpus:

### Site 1 — Single-product SaaS marketing site
- Profile: clean, minimalist, single brand color, generous spacing
- Expected brand: 1 clear primary color, no clear secondary
- Expected typography: 1 font family, 5-7 sizes following a 1.25 ratio
- Expected spacing: 4px or 8px base
- Expected component patterns: ≤ 5 (hero, feature, pricing card, footer, button)

### Site 2 — Multi-brand portfolio
- Profile: each product page has its own visual identity, shared chrome
- Expected brand: ambiguous (the algorithm might pick the chrome color or one of the page colors; either is correct)
- Expected typography: 2-3 families
- Expected component patterns: ≥ 10 (varied)

### Site 3 — E-commerce
- Profile: product cards everywhere, lots of imagery, secondary colors for badges
- Expected brand: 1 strong primary, possibly an accent for CTAs
- Expected component patterns: high occurrence count on the product-card pattern
- Expected breakpoints: at least 3 (mobile, tablet, desktop)

### Site 4 — Developer documentation
- Profile: lots of text, code blocks, sidebar navigation, light/dark mode
- Expected brand: 1 primary, 1 accent for links and headings
- Expected typography: 2 families (sans for body, mono for code)
- Expected spacing: usually 4px base, very regular

### Site 5 — News / editorial
- Profile: dense, photo-driven, multiple typefaces, complex layout grid
- Expected brand: subtle — could be the masthead color or a section accent
- Expected typography: ≥ 3 families
- Expected component patterns: many (article card, byline, headline variants, sidebar widgets)

> **Note for the implementer**: don't commit the actual URLs to this repo. Use a private `calibration.local.md` that's gitignored.

---

## The calibration process

### 1. Capture each site

```bash
for site in $CALIBRATION_SITES; do
    python -m scripts.run "$site" \
        --depth 2 --max-pages 30 \
        --output ./calibration/$(slugify "$site")
done
```

### 2. Score the output by hand

For each captured site, fill out a row in `calibration/scorecard.md`:

| Site | Brand primary detected | Match? | Type ratio detected | Match? | Spacing base | Match? | Component count | Reasonable? |
|---|---|---|---|---|---|---|---|---|
| Site 1 | `#1A73E8` | yes | 1.25 | yes | 4 | yes | 4 | yes |
| Site 2 | `#0F172A` | ambiguous | 1.333 | yes | 8 | yes | 12 | yes |
| ... | | | | | | | | |

A "yes" means you eyeballed the captured screenshots, mentally compared to the output, and agreed. "No" means the algorithm got it wrong.

### 3. Identify systematic failures

If 4 of 5 sites are wrong in the same direction (e.g., all brand colors come out too saturated, or all type scales are detected as 1.5 when they're really 1.25), that's a tuning signal.

If 1 of 5 sites is wrong, that's noise. Don't tune for it — it'll regress others.

### 4. Adjust constants

The knobs (all in `scripts/analyze_dna.py`):

- `K_CANDIDATES` — k values to try for color clustering. Larger range = better fit but slower.
- `SILHOUETTE_SAMPLE_FRAC` — fraction of points to use for silhouette score. Smaller = faster, less accurate.
- `NEUTRAL_SATURATION_MAX` — LAB chroma threshold below which a color is classified as neutral. Higher = more neutrals.
- `BRAND_FREQ_MULTIPLIER` — a cluster must appear at least this much × median frequency to be a brand color. Lower = more clusters become brand.
- `ACCENT_SATURATION_MIN` — minimum LAB chroma for accent classification. Higher = fewer accents.
- `SHADOW_MERGE_DELTA_E` — LAB color distance below which shadows are considered duplicates. Higher = more merging.
- `COMPONENT_MIN_OCCURRENCE` — a structural pattern must appear this many times to count as a component. Lower = more patterns found.
- `COMPONENT_RECURSION_DEPTH` — how deep the structural signature considers children. Higher = stricter pattern matching.
- `SPACING_MIN_OCCURRENCE` — minimum times a spacing value must appear to be included in the scale.

### 5. Re-run and re-score

After every constant change, re-run all 5 sites and update the scorecard. Track the deltas. If a change improves 4 sites and degrades 1, accept it. If 2-2 split, consider whether the constant choice is actually principled.

Commit constant changes with a message like:
```
Tune NEUTRAL_SATURATION_MAX from 5 to 8

Site 3 was misclassifying its slightly-tinted greys as accent. Tightening
the threshold fixed Site 3, kept Sites 1-2-4-5 correct. Calibration
scorecard updated.
```

---

## Snapshot tests

After calibration, snapshot the expected output of each calibration site so that later regressions are caught automatically:

```bash
for site_dir in ./calibration/*/; do
    cp $site_dir/analysis/design-tokens.json \
       ./tests/fixtures/calibration_expected/$(basename $site_dir)_tokens.json
done
```

Then `tests/test_calibration.py` (M5 milestone) compares the live output to these snapshots and fails on any non-trivial drift.

```python
@pytest.mark.calibration
def test_calibration_site_1():
    # Re-run analyzer against captured-site-1 inputs
    # Compare design-tokens.json output to snapshot
    # Tolerate ±1 in counts and color L*a*b* distance ≤ 3
    ...
```

The tolerance matters. Network variability and minor source changes can shift a cluster by a few points without anyone noticing. Don't fail on exact equality — fail on meaningful drift.

---

## When NOT to tune

- If you're optimizing for one specific site you happen to care about.
- If your test corpus is one site you're paid to support.
- If a colleague pushes back on a constant change and you can't articulate *why* it improves the median case.
- Anytime your reasoning includes "well, the algorithm is wrong here so the constant should be...".

Tuning constants is a forever maintenance task. Schedule it quarterly, not ad-hoc.

---

## Future: automated calibration

A more ambitious version of this could use a held-out validation set with hand-labeled "this is the brand color" ground truth and search the constant space programmatically (grid search, Bayesian optimization).

That's overkill for v0.1.0. Manual scoring against 5 sites is more useful than automated scoring against 50 — because the manual reviewer notices things the automated comparison would miss (e.g., "the algorithm said the brand color is X, which is technically the most-frequent saturated color, but a human would clearly say the brand color is Y based on where it's placed").

---

## Where the scorecard lives

`calibration/scorecard.md`. Not committed (each contributor's local data). The aggregated, anonymized form lives here in `references/calibration.md` as the corpus profiles above.
