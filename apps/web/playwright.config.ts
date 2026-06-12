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
      // Local (non-CI): pin the API to the docker-compose postgres/redis.
      // The repo-root .env points DATABASE_URL at PROD Supabase (and its
      // pooler caps at 15 session clients — e2e bursts exhaust it into
      // 500s). E2E must never touch prod data or prod budgets.
      command: process.env.CI
        ? 'cd ../.. && PYTHONPATH=. python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000'
        : 'cd ../.. && source .venv/bin/activate && PYTHONPATH=. DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5432/retarget_agent REDIS_URL=redis://localhost:6379/0 python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000',
      port: 8000,
      timeout: 30_000,
      reuseExistingServer: true,
    },
    {
      // Disable Clerk auth for E2E — fall back to JWT-based auth
      // that the auth.setup.ts can provision via the API.
      // Pin the API to localhost: .env.local points NEXT_PUBLIC_API_URL at
      // prod, so without the override the browser calls the prod API with a
      // locally-minted token — every API call 401s and bounces to /sign-in
      // (only instant-render assertions pass). CI has no .env.local, which
      // is why this only ever broke locally.
      command:
        "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY= CLERK_SECRET_KEY= NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev",
      port: 3000,
      timeout: 30_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
