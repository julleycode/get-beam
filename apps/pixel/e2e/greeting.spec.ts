import { expect, test } from "@playwright/test";
import { fixture, interceptGreeting, interceptIngest, settle } from "./harness";

// G4 — on-site company greeting (onsite-greeting). tracker.js must lazy-load
// greeting.js ONLY when data-greeting="on" AND consent is granted AND there is
// no GPC/DNT opt-out; greeting.js renders server text via textContent, ignores
// any non-200, and remembers a dismiss.

test("shown: consent not gated, attr on → badge rendered from server text", async ({ page }) => {
  await interceptIngest(page);
  const g = await interceptGreeting(page);
  await page.goto(fixture("greeting.html"));
  await expect(page.locator("#_rtaG ._rtaGt")).toHaveText("Welcome, Acme team!");
  expect(g.scriptLoads()).toBe(1);
  expect(g.apiCalls).toHaveLength(1);
  const u = new URL(g.apiCalls[0]);
  expect(u.searchParams.get("site_id")).toBe("test-site");
  expect(u.searchParams.get("v")).toBeTruthy();
});

test("text is rendered as text, never HTML", async ({ page }) => {
  await interceptIngest(page);
  await interceptGreeting(page, { show: true, template_id: "default", text: "<img src=x onerror=alert(1)>", cta_url: null });
  await page.goto(fixture("greeting.html"));
  await expect(page.locator("#_rtaG ._rtaGt")).toHaveText("<img src=x onerror=alert(1)>");
  expect(await page.locator("#_rtaG img").count()).toBe(0);
});

test("consent pending → greeting.js never requested; accept → loaded", async ({ page }) => {
  await interceptIngest(page);
  const g = await interceptGreeting(page);
  await page.goto(fixture("greeting-consent.html"));
  await settle(page, 500);
  expect(g.scriptLoads()).toBe(0);
  await page.evaluate(() => (window as any).beamConsent(true));
  await expect(page.locator("#_rtaG")).toBeVisible();
  expect(g.scriptLoads()).toBe(1);
});

test("consent declined → never requested", async ({ page }) => {
  await interceptIngest(page);
  const g = await interceptGreeting(page);
  await page.goto(fixture("greeting-consent.html"));
  await page.evaluate(() => (window as any).beamConsent(false));
  await settle(page, 500);
  expect(g.scriptLoads()).toBe(0);
  expect(await page.locator("#_rtaG").count()).toBe(0);
});

test("GPC → never requested", async ({ page }) => {
  await interceptIngest(page);
  const g = await interceptGreeting(page);
  await page.goto(fixture("greeting-gpc.html"));
  await settle(page, 500);
  expect(g.scriptLoads()).toBe(0);
});

test("attr off → greeting.js never requested", async ({ page }) => {
  await interceptIngest(page);
  const g = await interceptGreeting(page);
  await page.goto(fixture("base.html"));
  await settle(page, 500);
  expect(g.scriptLoads()).toBe(0);
  expect(g.apiCalls).toHaveLength(0);
});

test("server show:false (flag off / eyeball org) → nothing rendered", async ({ page }) => {
  await interceptIngest(page);
  const g = await interceptGreeting(page, { show: false });
  await page.goto(fixture("greeting.html"));
  await expect.poll(() => g.apiCalls.length).toBe(1);
  await settle(page, 300);
  expect(await page.locator("#_rtaG").count()).toBe(0);
});

test("non-200 ignored (429)", async ({ page }) => {
  await interceptIngest(page);
  const g = await interceptGreeting(page, { show: true, template_id: "default", text: "x", cta_url: null }, 429);
  await page.goto(fixture("greeting.html"));
  await expect.poll(() => g.apiCalls.length).toBe(1);
  await settle(page, 300);
  expect(await page.locator("#_rtaG").count()).toBe(0);
});

test("dismiss persists across reload", async ({ page }) => {
  await interceptIngest(page);
  const g = await interceptGreeting(page);
  await page.goto(fixture("greeting.html"));
  await page.locator("#_rtaG ._rtaGx").click();
  await expect(page.locator("#_rtaG")).toHaveCount(0);
  await page.reload();
  await settle(page, 500);
  expect(await page.locator("#_rtaG").count()).toBe(0);
  expect(g.apiCalls).toHaveLength(1); // no API call after dismiss
});
