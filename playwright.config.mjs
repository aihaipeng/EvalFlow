import {defineConfig} from "@playwright/test";

const e2ePort = Number(process.env.EVALFLOW_E2E_PORT || 8765);
const e2eBaseUrl = `http://127.0.0.1:${e2ePort}`;

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  expect: {timeout: 8_000},
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", {open: "never", outputFolder: ".pytest_tmp/playwright-report"}]],
  use: {baseURL: e2eBaseUrl, channel: "chromium", trace: "retain-on-failure", screenshot: "only-on-failure"},
  webServer: {
    command: "uv run python tests/e2e_server.py",
    url: e2eBaseUrl,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
