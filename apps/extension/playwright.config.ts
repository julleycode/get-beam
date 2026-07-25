import { defineConfig, devices } from "@playwright/test";

// Extension-scoped Playwright config. MV3 extensions can only be loaded into a
// persistent context launched with --load-extension (see e2e/harness.ts), so
// tests drive the context directly rather than through the default `page`
// fixture. A zero-infra static server hosts the fixture dashboard/attacker pages
// on localhost:3000 (a Beam origin in the manifest's externally_connectable /
// content_scripts matches, so the extension actually talks to it).
//
// externally_connectable / content_scripts only match https + localhost, and MV3
// service workers + --load-extension require a Chromium build — so only the
// chromium project is meaningful here (webkit/firefox don't support MV3 load).
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
    trace: "off",
    screenshot: "off",
    video: "off",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      // Beam-origin dashboard fixture (a manifest match → content script runs).
      command: "python3 -m http.server 3000 --directory e2e/fixtures",
      url: "http://localhost:3000/dashboard.html",
      reuseExistingServer: !process.env.CI,
      timeout: 20_000,
    },
    {
      // Non-Beam origin for the AC5 spoofed-origin test — port 3999 is NOT in
      // the manifest's matches, so the content script must never inject here.
      command: "python3 -m http.server 3999 --directory e2e/fixtures",
      url: "http://localhost:3999/attacker.html",
      reuseExistingServer: !process.env.CI,
      timeout: 20_000,
    },
  ],
});
