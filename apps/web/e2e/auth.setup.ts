import { test as setup, expect } from "@playwright/test";

const API_BASE = "http://localhost:8000";
const DEMO_EMAIL = "demo@retargetagent.com";
const DEMO_PASSWORD = "demo1234";

/**
 * Authenticate via API and save the token to localStorage
 * so all subsequent tests can reuse the auth state.
 */
setup("authenticate", async ({ page }) => {
  // Login via API to get token
  const res = await page.request.post(`${API_BASE}/api/v1/auth/login`, {
    data: { email: DEMO_EMAIL, password: DEMO_PASSWORD },
  });

  expect(res.ok()).toBeTruthy();
  const { access_token } = await res.json();
  expect(access_token).toBeTruthy();

  // Navigate to the app and set token in localStorage
  await page.goto("/");
  await page.evaluate((token) => {
    localStorage.setItem("auth_token", token);
  }, access_token);

  // Save auth state
  await page.context().storageState({ path: "e2e/.auth/user.json" });
});
