"""
Design DNA extraction. Implements the algorithms specified in
references/dna_extraction.md.

Inputs: every raw/pages/<slug>/computed-styles.json, plus raw CSS files.
Outputs: analysis/design-tokens.json + per-system files.

This module is heavy on numeric work. Read the spec doc before changing
any of the tuning constants below — they were chosen for specific reasons.
"""

from __future__ import annotations

import colorsys
import hashlib
import json
import logging
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from bs4 import BeautifulSoup
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from scripts.config import Config
from scripts.models import (
    AccentColors,
    BrandColors,
    BreakpointSystem,
    ColorCluster,
    ColorPalette,
    ComponentExample,
    ComponentPattern,
    ComponentPatterns,
    DesignTokens,
    FontFamilyDef,
    FontSize,
    IconLibrary,
    InlineSvg,
    MotionSystem,
    RadiusSystem,
    ShadowSystem,
    SpacingEntry,
    SpacingSystem,
    TokenValue,
    TypographyScale,
    TypographySystem,
    load_model,
    write_model,
)
from scripts.models import ComputedStylesDoc
from scripts.utils import ensure_dir


log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning knobs — see references/dna_extraction.md "Tuning knobs"
# ---------------------------------------------------------------------------

K_CANDIDATES = [6, 8, 12, 16, 20]
SILHOUETTE_SAMPLE_FRAC = 0.1
NEUTRAL_SATURATION_MAX = 5.0       # LAB chroma
BRAND_FREQ_MULTIPLIER = 2.0         # × median
ACCENT_SATURATION_MIN = 50.0
SHADOW_MERGE_DELTA_E = 5.0
SHADOW_MERGE_BLUR_PX = 2.0
COMPONENT_MIN_OCCURRENCE = 3
COMPONENT_RECURSION_DEPTH = 3
SPACING_MIN_OCCURRENCE = 3


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(config: Config) -> DesignTokens:
    """Read all computed-styles, run every sub-analyzer, write the outputs."""
    analysis_dir = ensure_dir(config.output_dir / "analysis")
    pages_dir = config.output_dir / "raw" / "pages"

    # Aggregate every element across every page
    elements: list[dict] = []
    css_texts: list[str] = []
    rendered_htmls: list[tuple[str, str]] = []   # (slug, html)
    for slug_dir in pages_dir.iterdir():
        if not slug_dir.is_dir():
            continue
        cs_path = slug_dir / "computed-styles.json"
        if cs_path.exists():
            doc = load_model(cs_path, ComputedStylesDoc)
            elements.extend([
                {"page": doc.page_slug, **e.model_dump()} for e in doc.elements
            ])
        rh = slug_dir / "rendered.html"
        if rh.exists():
            rendered_htmls.append((slug_dir.name, rh.read_text(errors="ignore")))

    assets_dir = config.output_dir / "raw" / "assets" / "stylesheets"
    if assets_dir.exists():
        for css_file in assets_dir.glob("*.css"):
            try:
                css_texts.append(css_file.read_text(errors="ignore"))
            except Exception:
                pass

    log.info(f"Analyzing {len(elements)} elements across {len(rendered_htmls)} pages")

    color = extract_colors(elements, css_texts)
    typography = extract_typography(elements, css_texts)
    spacing = extract_spacing(elements)
    radius = extract_radii(elements)
    shadow = extract_shadows(elements)
    motion = extract_motion(elements, css_texts)
    breakpoints = extract_breakpoints(css_texts)
    components = extract_components(rendered_htmls)
    icons = extract_icons(rendered_htmls, config)

    write_model(analysis_dir / "color-palette.json", color)
    write_model(analysis_dir / "typography-system.json", typography)
    write_model(analysis_dir / "spacing-system.json", spacing)
    write_model(analysis_dir / "radius-system.json", radius)
    write_model(analysis_dir / "shadow-system.json", shadow)
    write_model(analysis_dir / "motion-system.json", motion)
    write_model(analysis_dir / "breakpoints.json", breakpoints)
    write_model(analysis_dir / "component-patterns.json", components)
    write_model(analysis_dir / "icon-library.json", icons)

    tokens = DesignTokens(
        generated_at=datetime.utcnow(),
        color=color,
        typography=typography,
        spacing=spacing,
        radius=radius,
        shadow=shadow,
        motion=motion,
        breakpoint=breakpoints,
    )
    write_model(analysis_dir / "design-tokens.json", tokens)

    # Render CSS variables version
    _render_tokens_css(tokens, analysis_dir / "design-tokens.css")

    return tokens


# ---------------------------------------------------------------------------
# 1. Colors
# ---------------------------------------------------------------------------

def extract_colors(elements: list[dict], css_texts: list[str]) -> ColorPalette:
    raw_colors: Counter[tuple[int, int, int]] = Counter()
    color_keys = ("color", "background-color", "border-color", "outline-color", "fill", "stroke")
    for el in elements:
        styles = el.get("styles", {})
        for k in color_keys:
            rgb = _parse_color(styles.get(k, ""))
            if rgb:
                raw_colors[rgb] += 1
        # Gradient stops
        bg_image = styles.get("background-image", "")
        for stop in _parse_gradient_stops(bg_image):
            raw_colors[stop] += 1

    # Add raw CSS color literals
    for css in css_texts:
        for m in re.finditer(r"#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsla?\([^)]+\)", css):
            rgb = _parse_color(m.group(0))
            if rgb:
                raw_colors[rgb] += 1

    if not raw_colors:
        return ColorPalette()

    # Build LAB array weighted by count (replicate points by sqrt frequency)
    points: list[list[float]] = []
    rgb_list: list[tuple[int, int, int]] = []
    for rgb, cnt in raw_colors.items():
        lab = _rgb_to_lab(rgb)
        repeat = max(1, int(math.sqrt(cnt)))
        for _ in range(repeat):
            points.append(lab)
            rgb_list.append(rgb)
    X = np.array(points)

    # Choose k by silhouette score
    best_k = K_CANDIDATES[0]
    best_score = -1.0
    best_labels = None
    for k in K_CANDIDATES:
        if len(X) < k * 2:
            continue
        km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
        # Sample for silhouette
        if len(X) > 500:
            idx = np.random.choice(len(X), int(len(X) * SILHOUETTE_SAMPLE_FRAC), replace=False)
            score = silhouette_score(X[idx], km.labels_[idx])
        else:
            score = silhouette_score(X, km.labels_)
        if score > best_score:
            best_score = score
            best_k = k
            best_labels = km.labels_
            best_centroids = km.cluster_centers_

    if best_labels is None:
        return ColorPalette()

    # Build clusters: {centroid -> {members, size}}
    clusters: list[ColorCluster] = []
    for i, centroid_lab in enumerate(best_centroids):
        member_indices = np.where(best_labels == i)[0]
        if len(member_indices) == 0:
            continue
        member_rgbs = list({rgb_list[j] for j in member_indices})
        centroid_rgb = _lab_to_rgb(centroid_lab)
        size = sum(raw_colors[rgb] for rgb in member_rgbs)
        L, a, b = centroid_lab
        sat = math.sqrt(a*a + b*b)
        clusters.append(ColorCluster(
            centroid=_rgb_hex(centroid_rgb),
            size=size,
            members=[_rgb_hex(rgb) for rgb in member_rgbs],
            saturation=sat,
            lightness=L,
            classification="",   # filled below
        ))

    # Classify
    freqs = [c.size for c in clusters]
    median_freq = float(np.median(freqs)) if freqs else 0.0

    brand_candidates = []
    accent_candidates = []
    neutral_clusters = []
    tertiary = []

    for c in clusters:
        if c.saturation < NEUTRAL_SATURATION_MAX:
            c.classification = "neutral"
            neutral_clusters.append(c)
        elif c.size > median_freq * BRAND_FREQ_MULTIPLIER and c.saturation > 30:
            c.classification = "brand"
            brand_candidates.append(c)
        elif c.saturation > ACCENT_SATURATION_MIN and c.size < median_freq:
            c.classification = "accent"
            accent_candidates.append(c)
        else:
            c.classification = "tertiary"
            tertiary.append(c)

    # Brand: top 2 by frequency
    brand_candidates.sort(key=lambda x: -x.size)
    brand = BrandColors()
    if brand_candidates:
        brand.primary = TokenValue(value=brand_candidates[0].centroid, frequency=brand_candidates[0].size)
    if len(brand_candidates) > 1:
        brand.secondary = TokenValue(value=brand_candidates[1].centroid, frequency=brand_candidates[1].size)

    # Neutrals: bucket by lightness
    neutrals: dict[str, TokenValue] = {}
    for nc in neutral_clusters:
        bucket = _neutral_bucket(nc.lightness)
        if bucket not in neutrals or nc.size > (neutrals[bucket].frequency or 0):
            neutrals[bucket] = TokenValue(value=nc.centroid, frequency=nc.size)

    # Accents: classify by hue
    accent = AccentColors()
    for ac in accent_candidates:
        rgb = _hex_to_rgb(ac.centroid)
        h, _, _ = colorsys.rgb_to_hls(rgb[0]/255, rgb[1]/255, rgb[2]/255)
        h_deg = h * 360
        if 80 <= h_deg <= 160 and not accent.success:
            accent.success = TokenValue(value=ac.centroid, frequency=ac.size)
        elif 40 <= h_deg < 80 and not accent.warning:
            accent.warning = TokenValue(value=ac.centroid, frequency=ac.size)
        elif (h_deg >= 340 or h_deg < 20) and not accent.danger:
            accent.danger = TokenValue(value=ac.centroid, frequency=ac.size)
        elif 200 <= h_deg < 260 and not accent.info:
            accent.info = TokenValue(value=ac.centroid, frequency=ac.size)
        else:
            tertiary.append(ac)

    return ColorPalette(
        brand=brand,
        neutrals=neutrals,
        accent=accent,
        tertiary=[TokenValue(value=c.centroid, frequency=c.size) for c in tertiary],
        raw_clusters=clusters,
    )


def _neutral_bucket(L: float) -> str:
    # LAB L is in [0, 100]
    if L > 97: return "0"
    if L > 92: return "50"
    if L > 85: return "100"
    if L > 70: return "200"
    if L > 55: return "300"
    if L > 45: return "400"
    if L > 35: return "500"
    if L > 25: return "600"
    if L > 15: return "700"
    if L > 8:  return "800"
    if L > 3:  return "900"
    return "950"


# ---------------------------------------------------------------------------
# Color space conversions
# ---------------------------------------------------------------------------

def _parse_color(s: str) -> tuple[int, int, int] | None:
    s = (s or "").strip()
    if not s or s in ("transparent", "currentcolor", "inherit", "initial", "none"):
        return None
    # rgb / rgba
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    # hex
    if s.startswith("#"):
        h = s.lstrip("#")
        if len(h) == 3:
            return tuple(int(h[i]*2, 16) for i in range(3))   # type: ignore
        if len(h) in (6, 8):
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    # hsl
    m = re.match(r"hsla?\(\s*(\d+),\s*(\d+)%?\s*,\s*(\d+)%?", s)
    if m:
        h = int(m.group(1)) / 360
        s_val = int(m.group(2)) / 100
        l = int(m.group(3)) / 100
        r, g, b = colorsys.hls_to_rgb(h, l, s_val)
        return int(r*255), int(g*255), int(b*255)
    return None


def _parse_gradient_stops(bg: str) -> list[tuple[int, int, int]]:
    if "gradient" not in bg:
        return []
    stops = []
    for m in re.finditer(r"#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsla?\([^)]+\)", bg):
        rgb = _parse_color(m.group(0))
        if rgb:
            stops.append(rgb)
    return stops


def _rgb_to_lab(rgb: tuple[int, int, int]) -> list[float]:
    """sRGB → linear RGB → XYZ → LAB (D65)."""
    def lin(c):
        c /= 255.0
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
    r, g, b = (lin(c) for c in rgb)
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505
    x /= 0.95047; y /= 1.0; z /= 1.08883
    def f(t):
        return t ** (1/3) if t > 0.008856 else 7.787 * t + 16/116
    fx, fy, fz = f(x), f(y), f(z)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b_ = 200 * (fy - fz)
    return [L, a, b_]


def _lab_to_rgb(lab: list[float]) -> tuple[int, int, int]:
    L, a, b = lab
    fy = (L + 16) / 116
    fx = a / 500 + fy
    fz = fy - b / 200
    def fi(t):
        return t**3 if t**3 > 0.008856 else (t - 16/116) / 7.787
    x = fi(fx) * 0.95047
    y = fi(fy) * 1.0
    z = fi(fz) * 1.08883
    r = x *  3.2406 + y * -1.5372 + z * -0.4986
    g = x * -0.9689 + y *  1.8758 + z *  0.0415
    b_ = x * 0.0557 + y * -0.2040 + z *  1.0570
    def to_srgb(c):
        c = max(0.0, min(1.0, c))
        return 1.055 * (c ** (1/2.4)) - 0.055 if c > 0.0031308 else 12.92 * c
    return tuple(max(0, min(255, int(round(to_srgb(c) * 255)))) for c in (r, g, b_))   # type: ignore


def _rgb_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _hex_to_rgb(s: str) -> tuple[int, int, int]:
    h = s.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ---------------------------------------------------------------------------
# 2. Typography
# ---------------------------------------------------------------------------

def extract_typography(elements: list[dict], css_texts: list[str]) -> TypographySystem:
    family_counts: Counter[str] = Counter()
    sizes: Counter[float] = Counter()
    weights: Counter[int] = Counter()
    line_heights: list[float] = []
    letter_spacings: list[str] = []
    stacks_by_primary: dict[str, str] = {}

    for el in elements:
        styles = el.get("styles", {})
        if not (el.get("text") or "").strip():
            continue
        stack = styles.get("font-family", "")
        primary = _first_family(stack)
        if primary:
            family_counts[primary] += 1
            stacks_by_primary.setdefault(primary, stack)
        size = _parse_px(styles.get("font-size", ""))
        if size:
            sizes[round(size, 1)] += 1
        w = _parse_int(styles.get("font-weight", ""))
        if w:
            weights[w] += 1
        lh = _parse_lh(styles.get("line-height", ""), size)
        if lh:
            line_heights.append(lh)
        ls = styles.get("letter-spacing", "")
        if ls and ls != "normal":
            letter_spacings.append(ls)

    # Families
    families: dict[str, FontFamilyDef] = {}
    sorted_fams = family_counts.most_common()
    if sorted_fams:
        primary = sorted_fams[0][0]
        families["body"] = FontFamilyDef(stack=stacks_by_primary[primary], primary=primary)
        heading = primary
        for fam, _ in sorted_fams[1:]:
            if fam.lower() != primary.lower():
                heading = fam
                break
        families["heading"] = FontFamilyDef(stack=stacks_by_primary.get(heading, stacks_by_primary[primary]), primary=heading)

    # Scale
    scale = _detect_type_scale(sizes)

    # Line heights bucket
    lh_buckets = {"tight": 1.2, "normal": 1.5, "loose": 1.75}
    if line_heights:
        sorted_lh = sorted(line_heights)
        lh_buckets["tight"] = round(sorted_lh[len(sorted_lh)//8], 2)
        lh_buckets["normal"] = round(sorted_lh[len(sorted_lh)//2], 2)
        lh_buckets["loose"] = round(sorted_lh[len(sorted_lh)*7//8], 2)

    # Letter spacings
    ls_counts = Counter(letter_spacings)
    ls_buckets = {"normal": "0"}
    if ls_counts:
        most = ls_counts.most_common(3)
        ls_buckets = {f"v{i}": v for i, (v, _) in enumerate(most)}
        ls_buckets["normal"] = "0"

    return TypographySystem(
        families=families,
        scale=scale,
        weights=sorted(weights),
        line_heights=lh_buckets,
        letter_spacing=ls_buckets,
    )


def _first_family(stack: str) -> str | None:
    if not stack:
        return None
    parts = [p.strip().strip('"').strip("'") for p in stack.split(",")]
    parts = [p for p in parts if p and not p.startswith("-")]
    return parts[0] if parts else None


def _parse_px(s: str) -> float | None:
    m = re.match(r"([\d.]+)px", s or "")
    return float(m.group(1)) if m else None


def _parse_int(s: str) -> int | None:
    m = re.match(r"(\d+)", s or "")
    return int(m.group(1)) if m else None


def _parse_lh(s: str, size_px: float | None) -> float | None:
    s = (s or "").strip()
    if not s or s == "normal":
        return None
    if s.endswith("px") and size_px:
        return float(s[:-2]) / size_px
    try:
        return float(s)
    except ValueError:
        return None


COMMON_RATIOS = [1.067, 1.125, 1.2, 1.25, 1.333, 1.414, 1.5, 1.618]


def _detect_type_scale(sizes: Counter[float]) -> TypographyScale:
    if not sizes:
        return TypographyScale(ratio=None, base_px=16, sizes={})

    sorted_sizes = sorted(sizes.keys())
    # Pairwise ratios
    ratios: list[float] = []
    for i in range(len(sorted_sizes) - 1):
        if sorted_sizes[i] > 0:
            ratios.append(sorted_sizes[i+1] / sorted_sizes[i])
    if not ratios:
        return TypographyScale(ratio=None, base_px=sorted_sizes[0], sizes={})

    median_ratio = float(np.median(ratios))
    best_ratio = None
    best_dist = 1.0
    for r in COMMON_RATIOS:
        d = abs(median_ratio - r) / r
        if d < best_dist and d < 0.05:
            best_dist = d
            best_ratio = r

    # Most-frequent size = base
    base = sizes.most_common(1)[0][0]
    names = ["xs", "sm", "base", "lg", "xl", "2xl", "3xl", "4xl", "5xl", "6xl"]

    # Build size dict, anchored at base
    out: dict[str, FontSize] = {"base": FontSize(px=base, rem=base/16)}
    smaller = sorted([s for s in sorted_sizes if s < base], reverse=True)
    larger = sorted([s for s in sorted_sizes if s > base])
    down_names = ["sm", "xs", "2xs", "3xs"]
    up_names = ["lg", "xl", "2xl", "3xl", "4xl", "5xl", "6xl", "7xl"]
    for i, s in enumerate(smaller[:len(down_names)]):
        out[down_names[i]] = FontSize(px=s, rem=s/16)
    for i, s in enumerate(larger[:len(up_names)]):
        out[up_names[i]] = FontSize(px=s, rem=s/16)

    return TypographyScale(ratio=best_ratio, base_px=base, sizes=out)


# ---------------------------------------------------------------------------
# 3. Spacing
# ---------------------------------------------------------------------------

def extract_spacing(elements: list[dict]) -> SpacingSystem:
    values: Counter[float] = Counter()
    for el in elements:
        styles = el.get("styles", {})
        for prop in ("padding", "margin"):
            for part in (styles.get(prop) or "").split():
                v = _parse_px(part)
                if v is not None:
                    values[v] += 1
        # Also gap
        gap = _parse_px(styles.get("gap", ""))
        if gap is not None:
            values[gap] += 1

    if not values:
        return SpacingSystem(base_unit_px=4, scale={}, raw_values=[])

    nonzero = [v for v in values if v > 0]
    gcd = nonzero[0]
    for v in nonzero[1:]:
        gcd = math.gcd(int(gcd), int(v))
        if gcd == 1:
            break
    base = max(int(gcd), 4)   # never below 4

    scale: dict[str, SpacingEntry] = {}
    for v, count in values.items():
        if count < SPACING_MIN_OCCURRENCE:
            continue
        if base > 0 and v % base == 0:
            idx = int(v / base)
            scale[str(idx)] = SpacingEntry(px=v, rem=v/16)
    return SpacingSystem(
        base_unit_px=base,
        scale=dict(sorted(scale.items(), key=lambda kv: int(kv[0]))),
        raw_values=sorted(values),
    )


# ---------------------------------------------------------------------------
# 4. Radii
# ---------------------------------------------------------------------------

def extract_radii(elements: list[dict]) -> RadiusSystem:
    values: Counter[int] = Counter()
    for el in elements:
        styles = el.get("styles", {})
        for part in (styles.get("border-radius") or "").split():
            v = _parse_px(part)
            if v is not None and v > 0:
                values[round(v)] += 1
            elif part.endswith("%"):
                values[9999] += 1
    if not values:
        return RadiusSystem(scale={"none": 0})

    sorted_vals = sorted(set(values))
    names = ["sm", "base", "md", "lg", "xl", "2xl", "3xl"]
    scale: dict[str, int] = {"none": 0}
    for i, v in enumerate(sorted_vals[:len(names)]):
        scale[names[i]] = v
    if 9999 in values:
        scale["full"] = 9999
    return RadiusSystem(scale=scale)


# ---------------------------------------------------------------------------
# 5. Shadows
# ---------------------------------------------------------------------------

def extract_shadows(elements: list[dict]) -> ShadowSystem:
    counts: Counter[str] = Counter()
    for el in elements:
        sh = (el.get("styles") or {}).get("box-shadow", "")
        if sh and sh != "none":
            counts[sh] += 1
    if not counts:
        return ShadowSystem(scale={"none": "none"})

    top = [v for v, _ in counts.most_common(8)]
    names = ["xs", "sm", "base", "md", "lg", "xl", "2xl"]
    inner: dict[str, str] = {}
    scale: dict[str, str] = {"none": "none"}
    outer = [v for v in top if "inset" not in v]
    inners = [v for v in top if "inset" in v]
    for i, v in enumerate(outer[:len(names)]):
        scale[names[i]] = v
    for i, v in enumerate(inners[:3]):
        inner[names[i]] = v
    return ShadowSystem(scale=scale, inner=inner)


# ---------------------------------------------------------------------------
# 6. Motion
# ---------------------------------------------------------------------------

def extract_motion(elements: list[dict], css_texts: list[str]) -> MotionSystem:
    durations: Counter[str] = Counter()
    easings: Counter[str] = Counter()
    for el in elements:
        t = (el.get("styles") or {}).get("transition", "")
        for m in re.finditer(r"(\d+(?:\.\d+)?)(ms|s)", t):
            v = float(m.group(1))
            if m.group(2) == "s":
                v *= 1000
            durations[f"{int(v)}ms"] += 1
        for m in re.finditer(r"cubic-bezier\([^)]+\)|ease-in-out|ease-in|ease-out|ease|linear|step-start|step-end", t):
            easings[m.group(0)] += 1

    dur_names = ["instant", "fast", "base", "slow", "slower"]
    top_durations = [v for v, _ in durations.most_common(len(dur_names))]
    dur_dict = {n: top_durations[i] if i < len(top_durations) else f"{(i+1)*100}ms"
                for i, n in enumerate(dur_names)}

    easing_names = ["linear", "in", "out", "in-out"]
    top_easings = [v for v, _ in easings.most_common(len(easing_names))]
    easing_dict = {n: top_easings[i] if i < len(top_easings) else "ease"
                   for i, n in enumerate(easing_names)}

    # Keyframes from CSS
    keyframes: dict[str, dict[str, str]] = {}
    for css in css_texts:
        for m in re.finditer(r"@keyframes\s+([\w-]+)\s*\{([^{}]+(?:\{[^{}]*\}[^{}]*)*)\}", css):
            name = m.group(1)
            keyframes[name] = {"raw": m.group(2)[:200]}

    return MotionSystem(duration=dur_dict, easing=easing_dict, keyframes=keyframes)


# ---------------------------------------------------------------------------
# 7. Breakpoints
# ---------------------------------------------------------------------------

def extract_breakpoints(css_texts: list[str]) -> BreakpointSystem:
    widths: Counter[int] = Counter()
    for css in css_texts:
        for m in re.finditer(r"\(\s*(min|max)-width:\s*(\d+)px\s*\)", css):
            widths[int(m.group(2))] += 1
    if not widths:
        return BreakpointSystem(scale={}, raw=[])

    sorted_w = sorted(widths)
    deduped: list[int] = []
    for w in sorted_w:
        if not deduped or abs(w - deduped[-1]) > 10:
            deduped.append(w)

    names = ["sm", "md", "lg", "xl", "2xl"]
    scale: dict[str, str] = {}
    for i, w in enumerate(deduped[:len(names)]):
        scale[names[i]] = f"{w}px"
    return BreakpointSystem(scale=scale, raw=deduped)


# ---------------------------------------------------------------------------
# 8. Components
# ---------------------------------------------------------------------------

def extract_components(rendered_htmls: list[tuple[str, str]]) -> ComponentPatterns:
    signatures: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    classes_by_sig: dict[str, Counter[str]] = defaultdict(Counter)

    for slug, html in rendered_htmls:
        soup = BeautifulSoup(html, "lxml")
        for el in soup.find_all(True):
            if not (el.get("class") or el.get("role")):
                continue
            sig = _structural_signature(el, depth=COMPONENT_RECURSION_DEPTH)
            sig_hash = hashlib.sha1(json.dumps(sig).encode()).hexdigest()[:10]
            path = _css_path(el)
            snippet = str(el)[:400]
            signatures[sig_hash].append((slug, path, snippet))
            for c in (el.get("class") or []):
                classes_by_sig[sig_hash][c] += 1

    patterns: list[ComponentPattern] = []
    for sig_hash, occurrences in signatures.items():
        if len(occurrences) < COMPONENT_MIN_OCCURRENCE:
            continue
        first_html = occurrences[0][2]
        first_el = BeautifulSoup(first_html, "lxml").find()
        if first_el is None:
            continue
        role_guess = _guess_component_role(first_el)
        common_classes = [c for c, _ in classes_by_sig[sig_hash].most_common(5)]
        examples = [
            ComponentExample(page=p, path=path, html_snippet=html_snippet)
            for p, path, html_snippet in occurrences[:5]
        ]
        sig_struct = _structural_signature(first_el, depth=COMPONENT_RECURSION_DEPTH)
        patterns.append(ComponentPattern(
            id=f"p_{sig_hash}",
            role_guess=role_guess,
            occurrence_count=len(occurrences),
            signature=sig_struct,
            common_classes=common_classes,
            examples=examples,
        ))

    patterns.sort(key=lambda p: -p.occurrence_count)
    return ComponentPatterns(patterns=patterns)


def _structural_signature(el, depth: int) -> list[Any]:
    if depth <= 0:
        return [el.name, None, None, []]
    classes = el.get("class") or []
    class_prefix = None
    if classes:
        first = classes[0]
        # First two BEM-ish segments
        parts = re.split(r"[_-]{1,2}", first)
        class_prefix = "_".join(parts[:2]) if len(parts) > 1 else first
    role = el.get("role")
    children_sigs = []
    for child in el.find_all(recursive=False):
        children_sigs.append(_structural_signature(child, depth - 1))
        if len(children_sigs) >= 6:
            break
    return [el.name, role, class_prefix, children_sigs]


def _css_path(el) -> str:
    parts = []
    cur = el
    for _ in range(5):
        if cur.parent is None or cur.name == "[document]":
            break
        siblings = [s for s in cur.parent.find_all(cur.name, recursive=False)]
        idx = siblings.index(cur) if cur in siblings else 0
        parts.append(f"{cur.name}:nth({idx})")
        cur = cur.parent
    return ">".join(reversed(parts))


def _guess_component_role(el) -> str:
    tag = el.name
    classes = " ".join(el.get("class") or []).lower()
    role = (el.get("role") or "").lower()
    if tag == "button" or role == "button" or "btn" in classes:
        return "button"
    if tag == "nav" or role == "navigation":
        return "navigation"
    if "card" in classes or "tile" in classes:
        return "card"
    if tag == "header" or role == "banner":
        return "header"
    if tag == "footer" or role == "contentinfo":
        return "footer"
    if role == "dialog" or "modal" in classes:
        return "modal"
    if tag == "form":
        return "form"
    if tag in ("h1", "h2", "h3"):
        return "heading"
    return "unknown"


# ---------------------------------------------------------------------------
# 9. Icons
# ---------------------------------------------------------------------------

def extract_icons(rendered_htmls: list[tuple[str, str]], config: Config) -> IconLibrary:
    icons_dir = ensure_dir(config.output_dir / "analysis" / "icons")
    svgs: dict[str, InlineSvg] = {}

    for slug, html in rendered_htmls:
        soup = BeautifulSoup(html, "lxml")
        for svg in soup.find_all("svg"):
            normalized = _normalize_svg(str(svg))
            h = hashlib.sha1(normalized.encode()).hexdigest()[:10]
            if h not in svgs:
                path = icons_dir / f"{h}.svg"
                path.write_text(normalized)
                svgs[h] = InlineSvg(
                    hash=h,
                    path=str(path.relative_to(config.output_dir)),
                    used_on=[slug],
                    guessed_name=_guess_icon_name(normalized),
                    viewBox=svg.get("viewBox"),
                )
            else:
                if slug not in svgs[h].used_on:
                    svgs[h].used_on.append(slug)

    return IconLibrary(inline_svgs=list(svgs.values()), icon_fonts=[])


def _normalize_svg(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _guess_icon_name(svg: str) -> str:
    # Very crude — look at the path data for hints
    if "M3 12h18" in svg or "M4 6h16" in svg:
        return "menu"
    if "M6 18L18 6" in svg or "M18 6L6 18" in svg:
        return "close"
    return "unnamed"


# ---------------------------------------------------------------------------
# CSS rendering
# ---------------------------------------------------------------------------

def _render_tokens_css(tokens: DesignTokens, out_path: Path) -> None:
    lines = [":root {"]
    if tokens.color.brand.primary:
        lines.append(f"  --color-brand-primary: {tokens.color.brand.primary.value};")
    if tokens.color.brand.secondary:
        lines.append(f"  --color-brand-secondary: {tokens.color.brand.secondary.value};")
    for k, v in tokens.color.neutrals.items():
        lines.append(f"  --color-neutral-{k}: {v.value};")
    for k, v in (("success", tokens.color.accent.success),
                 ("warning", tokens.color.accent.warning),
                 ("danger",  tokens.color.accent.danger),
                 ("info",    tokens.color.accent.info)):
        if v:
            lines.append(f"  --color-accent-{k}: {v.value};")
    for k, v in tokens.typography.scale.sizes.items():
        lines.append(f"  --font-size-{k}: {v.rem}rem;")
    for k, v in tokens.spacing.scale.items():
        lines.append(f"  --space-{k}: {v.rem}rem;")
    for k, v in tokens.radius.scale.items():
        val = "9999px" if v == 9999 else f"{v}px"
        lines.append(f"  --radius-{k}: {val};")
    for k, v in tokens.shadow.scale.items():
        lines.append(f"  --shadow-{k}: {v};")
    for k, v in tokens.motion.duration.items():
        lines.append(f"  --duration-{k}: {v};")
    for k, v in tokens.motion.easing.items():
        lines.append(f"  --easing-{k}: {v};")
    for k, v in tokens.breakpoint.scale.items():
        lines.append(f"  --breakpoint-{k}: {v};")
    lines.append("}")
    out_path.write_text("\n".join(lines))
