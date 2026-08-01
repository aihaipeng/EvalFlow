import { resolve } from "node:path";

import { defineConfig } from "vite";

export default defineConfig({
  base: "/assets/vite/",
  build: {
    outDir: "web/static/assets/vite",
    emptyOutDir: true,
    manifest: true,
    sourcemap: true,
    target: "es2020",
    rollupOptions: {
      input: {
        "test-sets": resolve("web/frontend/test-sets.jsx"),
        "model-providers": resolve("web/frontend/model-providers.jsx"),
        "workflow-canvas": resolve("web/frontend/workflow-canvas.jsx"),
        "batch-runs": resolve("web/frontend/batch-runs.jsx"),
      },
      output: {
        entryFileNames: "[name]-[hash].js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: "[name]-[hash][extname]",
      },
    },
  },
});
