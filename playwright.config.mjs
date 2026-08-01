import {defineConfig} from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  expect: {timeout: 8_000},
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", {open: "never", outputFolder: ".pytest_tmp/playwright-report"}]],
  use: {baseURL: "http://127.0.0.1:8765", channel: "chromium", trace: "retain-on-failure", screenshot: "only-on-failure"},
  webServer: {
    command: "uv run python tests/e2e_server.py",
    url: "http://127.0.0.1:8765",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
