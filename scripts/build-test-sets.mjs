import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";

import { build } from "esbuild";

const outputBase = "web/static/assets/test-sets";

await build({
  entryPoints: ["web/frontend/test-sets.jsx"],
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "es2020",
  minify: true,
  legalComments: "linked",
  outfile: `${outputBase}.js`,
  logLevel: "info",
});

for (const path of [`${outputBase}.js`, `${outputBase}.css`, `${outputBase}.js.LEGAL.txt`]) {
  const content = await readFile(path, "utf8");
  const normalized = content.replace(/[ \t]+$/gm, "");
  if (normalized !== content) await writeFile(path, normalized, "utf8");
}

const bundleContent = await readFile(`${outputBase}.js`, "utf8");
const bundleVersion = createHash("sha256").update(bundleContent).digest("hex").slice(0, 12);
const styleContent = await readFile(`${outputBase}.css`, "utf8");
const styleVersion = createHash("sha256").update(styleContent).digest("hex").slice(0, 12);
const indexPath = "web/static/index.html";
const indexContent = await readFile(indexPath, "utf8");
const versionedScriptIndex = indexContent.replace(
  /\/assets\/test-sets\.js(?:\?v=[^"']+)?/,
  `/assets/test-sets.js?v=${bundleVersion}`,
);
const versionedIndex = versionedScriptIndex.replace(
  /\/assets\/test-sets\.css(?:\?v=[^"']+)?/,
  `/assets/test-sets.css?v=${styleVersion}`,
);
if (versionedIndex !== indexContent) await writeFile(indexPath, versionedIndex, "utf8");
