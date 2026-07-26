import { test, expect } from "@playwright/test";
import {
  launchExtension,
  seedLinkedInCookie,
  dashboardUrl,
  attackerUrl,
  type LoadedExtension,
} from "./harness";

// Onboarding wizard's read-only signed-in probe (plan D5).
// AC5: the response shape structurally contains no cookie / userAgent field.
// AC6: the probe is reachable ONLY over the Chrome-verified D6 channel — a
// non-Beam origin gets no answer at all (mirrors spoofed-origin.spec.ts).

let ext: LoadedExtension;

test.beforeEach(async () => {
  ext = await launchExtension();
});

test.afterEach(async () => {
  await ext.context.close();
});

test("AC5/AC6: Beam origin gets a well-formed status-only response (signed in)", async () => {
  await seedLinkedInCookie(ext.context);
  const page = await ext.context.newPage();
  await page.goto(dashboardUrl(ext.extensionId));

  const result = await page.evaluate(() =>
    (
      window as unknown as {
        trySessionCheck: () => Promise<{ status: string; response?: Record<string, unknown> }>;
      }
    ).trySessionCheck()
  );

  expect(result.status).toBe("answered");
  expect(result.response).toEqual({ signedIn: true });
  // AC5: explicit key-presence assertion, not just a falsy check.
  expect(Object.keys(result.response ?? {})).toEqual(["signedIn"]);
});

test("AC5: not signed in → status-only failure, still no cookie key", async () => {
  const page = await ext.context.newPage();
  await page.goto(dashboardUrl(ext.extensionId));

  const result = await page.evaluate(() =>
    (
      window as unknown as {
        trySessionCheck: () => Promise<{ status: string; response?: Record<string, unknown> }>;
      }
    ).trySessionCheck()
  );

  expect(result.status).toBe("answered");
  expect(result.response?.signedIn).toBe(false);
  expect(Object.keys(result.response ?? {}).sort()).toEqual(["reason", "signedIn"]);
});

test("AC6: D6 channel rejects a session-check from a non-Beam origin", async () => {
  await seedLinkedInCookie(ext.context);
  const page = await ext.context.newPage();
  await page.goto(attackerUrl());

  const result = await page.evaluate(
    (extId) =>
      (window as unknown as { trySessionCheck: (id: string) => Promise<string> }).trySessionCheck(
        extId
      ),
    ext.extensionId
  );

  // "threw" = chrome.runtime isn't even exposed to this non-Beam origin;
  // "rejected" = exposed but Chrome delivered no message. Both prove the probe
  // cannot be used as a cross-origin signed-in oracle.
  expect(["rejected", "threw"]).toContain(result);
});
