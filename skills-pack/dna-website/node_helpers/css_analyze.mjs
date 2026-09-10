#!/usr/bin/env node
/**
 * CSS AST analysis. Used by the Python analyzer for hard parts that BeautifulSoup
 * can't handle: nested at-rules, custom property resolution, complex selectors.
 *
 * Usage:
 *   node css_analyze.mjs <css-file>
 *   echo '...' | node css_analyze.mjs -
 *
 * Outputs JSON to stdout:
 *   {
 *     custom_properties: { "--foo": "value" },
 *     media_queries: ["(min-width: 768px)", ...],
 *     keyframes: ["fade-in", "slide-up", ...],
 *     font_faces: [{ family, src, weight, style }],
 *     selectors_used: ["...."]   // top-level selectors only
 *   }
 */

import { parse, walk } from "css-tree";
import { readFileSync } from "node:fs";

const arg = process.argv[2];
if (!arg) {
  console.error("Usage: css_analyze.mjs <file|->");
  process.exit(2);
}

const css = arg === "-" ? readFileSync(0, "utf-8") : readFileSync(arg, "utf-8");

let ast;
try {
  ast = parse(css);
} catch (e) {
  console.error("Parse failed:", e.message);
  process.exit(1);
}

const customProperties = {};
const mediaQueries = new Set();
const keyframes = new Set();
const fontFaces = [];
const selectors = new Set();

walk(ast, (node) => {
  if (node.type === "Declaration" && node.property?.startsWith("--")) {
    customProperties[node.property] = serialize(node.value);
  }
  if (node.type === "Atrule") {
    if (node.name === "media" && node.prelude) {
      mediaQueries.add(serialize(node.prelude));
    } else if (node.name === "keyframes" && node.prelude) {
      keyframes.add(serialize(node.prelude));
    } else if (node.name === "font-face" && node.block) {
      const face = { family: null, src: null, weight: null, style: null };
      walk(node.block, (d) => {
        if (d.type === "Declaration") {
          if (d.property === "font-family") face.family = serialize(d.value).replace(/['"]/g, "");
          if (d.property === "src") face.src = serialize(d.value);
          if (d.property === "font-weight") face.weight = serialize(d.value);
          if (d.property === "font-style") face.style = serialize(d.value);
        }
      });
      fontFaces.push(face);
    }
  }
  if (node.type === "Rule" && node.prelude) {
    selectors.add(serialize(node.prelude));
  }
});

function serialize(node) {
  if (!node) return "";
  if (typeof node === "string") return node;
  // Best-effort serialization via css-tree's generate
  try {
    const { generate } = require("css-tree");
    return generate(node);
  } catch {
    return "";
  }
}

process.stdout.write(JSON.stringify({
  custom_properties: customProperties,
  media_queries: [...mediaQueries],
  keyframes: [...keyframes],
  font_faces: fontFaces,
  selectors_used: [...selectors],
}, null, 2));
