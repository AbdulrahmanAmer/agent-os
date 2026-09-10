#!/usr/bin/env node
/**
 * Font metadata inspection via fontkit. Reads a font file and emits
 * its actual family name, subfamily, weight, italic flag, and supported
 * scripts.
 *
 * Usage:
 *   node font_inspect.mjs <font-file>
 *
 * Useful because @font-face declarations can specify any family name,
 * but the embedded metadata is canonical.
 */

import fontkit from "fontkit";
import { readFileSync, statSync } from "node:fs";

const arg = process.argv[2];
if (!arg) {
  console.error("Usage: font_inspect.mjs <font-file>");
  process.exit(2);
}

let font;
try {
  font = fontkit.openSync(arg);
} catch (e) {
  console.error("Open failed:", e.message);
  process.exit(1);
}

const result = {
  file: arg,
  size_bytes: statSync(arg).size,
  family: font.familyName,
  subfamily: font.subfamilyName,
  full_name: font.fullName,
  weight: weightFromSubfamily(font.subfamilyName),
  italic: /italic|oblique/i.test(font.subfamilyName || ""),
  units_per_em: font.unitsPerEm,
  num_glyphs: font.numGlyphs,
  scripts: font.availableFeatures ? Object.keys(font.scripts || {}) : [],
};

function weightFromSubfamily(name) {
  if (!name) return 400;
  const map = {
    thin: 100, hairline: 100,
    extralight: 200, ultralight: 200,
    light: 300,
    regular: 400, normal: 400, book: 400,
    medium: 500,
    semibold: 600, demibold: 600,
    bold: 700,
    extrabold: 800, ultrabold: 800,
    black: 900, heavy: 900,
  };
  const lower = name.toLowerCase();
  for (const key in map) if (lower.includes(key)) return map[key];
  return 400;
}

process.stdout.write(JSON.stringify(result, null, 2));
