import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";

import { build } from "esbuild";

const outputBase = "web/static/assets/workflow-canvas";

await build({
  entryPoints: ["web/frontend/workflow-canvas.jsx"],
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "es2020",
  minify: true,
  legalComments: "linked",
  external: ["/assets/*"],
  outfile: `${outputBase}.js`,
  logLevel: "info",
});

for (const path of [`${outputBase}.js`, `${outputBase}.css`, `${outputBase}.js.LEGAL.txt`]) {
  const content = await readFile(path, "utf8");
  const normalized = content.replace(/[ \t]+$/gm, "");
  if (normalized !== content) {
    await writeFile(path, normalized, "utf8");
  }
}

const bundleContent = await readFile(`${outputBase}.js`, "utf8");
const bundleVersion = createHash("sha256").update(bundleContent).digest("hex").slice(0, 12);
const executionContent = await readFile("web/static/execution.js", "utf8");
const executionVersion = createHash("sha256").update(executionContent).digest("hex").slice(0, 12);
const indexPath = "web/static/index.html";
const indexContent = await readFile(indexPath, "utf8");
const versionedWorkflowIndex = indexContent.replace(
  /\/assets\/workflow-canvas\.js(?:\?v=[^"']+)?/,
  `/assets/workflow-canvas.js?v=${bundleVersion}`,
);
const versionedIndex = versionedWorkflowIndex.replace(
    /\/execution\.js(?:\?v=[^"']+)?/,
    `/execution.js?v=${executionVersion}`,
);
if (versionedIndex !== indexContent) {
  await writeFile(indexPath, versionedIndex, "utf8");
}
