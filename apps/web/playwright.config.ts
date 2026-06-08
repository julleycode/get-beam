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
      command: process.env.CI
        ? 'cd ../.. && PYTHONPATH=. python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000'
        : 'cd ../.. && source .venv/bin/activate && PYTHONPATH=. python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000',
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
