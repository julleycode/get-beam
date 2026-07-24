import { defineConfig, devices } from "@playwright/test";

// Pixel-scoped Playwright config — deliberately separate from apps/web's
// dashboard config. tracker.js has zero dependency on the Next.js app, so this
// harness serves only static fixture HTML (python http.server, zero npm infra)
// and intercepts the pixel's ingest POST via page.route (no real API server).
//
// Browser projects: chromium (always cached locally), webkit + firefox are
// declared for the Phase 2 / AC5 cross-browser autofill matrix. In a sandbox
// without those binaries cached, run `--project=chromium` only; webkit/firefox
// are a documented known-gap (see plan Phase 0 checklist item 7).
export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  timeout: 30_000,

  use: {
    baseURL: "http://127.0.0.1:8788",
    trace: "off",
    screenshot: "off",
    video: "off",
  },

  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
  ],

  // Zero-infra static server for fixture HTML + the unminified tracker source.
  // Fixtures live at /e2e/fixtures/*.html; the pixel loads from /src/tracker.js.
  webServer: {
    command: "python3 -m http.server 8788",
    url: "http://127.0.0.1:8788/src/tracker.js",
    reuseExistingServer: !process.env.CI,
    timeout: 20_000,
  },
});
