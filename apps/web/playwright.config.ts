import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [["html", { open: "never" }], ["list"]],
  timeout: 60_000,

  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    // Setup project: authenticate once
    {
      name: "setup",
      testMatch: /auth\.setup\.ts/,
    },
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        storageState: "e2e/.auth/user.json",
      },
      dependencies: ["setup"],
    },
  ],

  /* Reuse already-running dev servers */
  webServer: [
    {
      // Local branch invokes the venv interpreter by explicit path on purpose:
      // Playwright runs webServer.command through /bin/sh, which has no `source`
      // builtin, and macOS has no bare `python` on PATH (only python3 / the venv).
      // Do NOT "fix" this back to `source .venv/bin/activate && python ...` —
      // that fails with `python: command not found` (exit 127).
      command: process.env.CI
        ? 'cd ../.. && PYTHONPATH=. python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000'
        : 'cd ../.. && PYTHONPATH=. .venv/bin/python3.11 -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000',
      port: 8000,
      timeout: 30_000,
      reuseExistingServer: true,
    },
    {
      // Disable Clerk auth for E2E — fall back to JWT-based auth
      // that the auth.setup.ts can provision via the API.
      command: "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY= CLERK_SECRET_KEY= npm run dev",
      port: 3000,
      timeout: 30_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
