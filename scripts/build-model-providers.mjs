import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { build } from "esbuild";

const output = "web/static/assets/model-providers.js";
await build({
  entryPoints: ["web/frontend/model-providers.jsx"], bundle: true, format: "iife",
  platform: "browser", target: "es2020", minify: true, legalComments: "linked",
  outfile: output, logLevel: "info",
});
const content = await readFile(output, "utf8");
const normalized = content.replace(/[ \t]+$/gm, "");
if (normalized !== content) await writeFile(output, normalized, "utf8");
const version = createHash("sha256").update(normalized).digest("hex").slice(0, 12);
const indexPath = "web/static/index.html";
const index = await readFile(indexPath, "utf8");
const next = index.replace(/\/assets\/model-providers\.js(?:\?v=[^"']+)?/, `/assets/model-providers.js?v=${version}`);
if (next !== index) await writeFile(indexPath, next, "utf8");
