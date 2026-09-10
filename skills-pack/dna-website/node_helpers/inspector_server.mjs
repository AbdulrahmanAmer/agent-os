#!/usr/bin/env node
/**
 * Local inspector server for browsing a DNA-website output offline.
 *
 * Usage:
 *   node inspector_server.mjs <path-to-output>/inspector [--port 7777]
 *
 * Serves:
 *   /                → index.html (page list with thumbnails)
 *   /pages/:slug     → rewritten HTML for a single page
 *   /tokens          → CSS variable overlay
 *   /manifest.json   → metadata
 *   /raw/*           → original captured assets (read-only)
 */

import express from "express";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";
import open from "open";
import chalk from "chalk";

const __dirname = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const inspectorDir = resolve(args[0] || ".");
const outputDir = resolve(inspectorDir, "..");
const port = parseInt(process.env.INSPECTOR_PORT || "7777", 10);
const noOpen = process.env.INSPECTOR_NO_OPEN === "1";

if (!existsSync(join(inspectorDir, "index.html"))) {
  console.error(chalk.red(`No index.html found in ${inspectorDir}`));
  console.error("Did the report stage finish? Look for inspector/ inside the run output.");
  process.exit(1);
}

const app = express();
app.use(express.static(inspectorDir));
// Serve the parent output dir under /raw so HTML pages can reference assets
// using paths like ../../raw/assets/images/abc.png that the rewrite emitted.
app.use("/raw", express.static(join(outputDir, "raw")));
app.use("/analysis", express.static(join(outputDir, "analysis")));

app.listen(port, () => {
  const url = `http://localhost:${port}`;
  console.log(chalk.green(`✓ Inspector running at ${url}`));
  console.log(chalk.dim(`  Serving ${inspectorDir}`));
  if (!noOpen) {
    open(url).catch(() => {});
  }
});
