import { test, expect } from "@playwright/test";
import {
  launchExtension,
  seedLinkedInCookie,
  dashboardUrl,
  type LoadedExtension,
} from "./harness";

// AC1: extension installed + LinkedIn signed in → one-click connect reaches the
// "connected" state, via the D6 externally_connectable channel. Fake li_at
// seeded directly into the cookie jar (OI-1-probed technique — no linkedin.com
// navigation needed).
// AC10: refresh/reconnect reuses the identical one-click flow.

let ext: LoadedExtension;

test.beforeEach(async () => {
  ext = await launchExtension();
  await seedLinkedInCookie(ext.context);
});

test.afterEach(async () => {
  await ext.context.close();
});

test("AC1: one-click connect reaches connected state", async () => {
  const page = await ext.context.newPage();
  await page.goto(dashboardUrl(ext.extensionId));

  await page.click("#connect");

  await expect(page.locator("#status")).toHaveText("connected", {
    timeout: 10_000,
  });
});

test("AC10: refresh/reconnect reuses the identical flow", async () => {
  const page = await ext.context.newPage();
  await page.goto(dashboardUrl(ext.extensionId));

  // First connect.
  await page.click("#connect");
  await expect(page.locator("#status")).toHaveText("connected");

  // Refresh with a rotated cookie — identical button, identical flow.
  await seedLinkedInCookie(ext.context, "AQEDA-fake-li_at-rotated");
  await page.evaluate(() => {
    document.getElementById("status")!.textContent = "idle";
  });
  await page.click("#connect");
  await expect(page.locator("#status")).toHaveText("connected");
});
