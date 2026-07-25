import { test, expect } from "@playwright/test";
import {
  launchExtension,
  seedLinkedInCookie,
  attackerUrl,
  type LoadedExtension,
} from "./harness";

// AC5: cookie never reaches a non-Beam origin. A page on a non-Beam origin
// (port 3999, not in the manifest matches) must (a) not receive the content
// script, and (b) not get an answer from the D6 externally_connectable channel.

let ext: LoadedExtension;

test.beforeEach(async () => {
  ext = await launchExtension();
  await seedLinkedInCookie(ext.context);
});

test.afterEach(async () => {
  await ext.context.close();
});

test("AC5: content script is NOT injected on a non-Beam origin", async () => {
  const page = await ext.context.newPage();
  await page.goto(attackerUrl());
  await expect(page.locator("#injected")).toHaveText("not-injected");
});

test("AC5: D6 channel rejects a request from a non-Beam origin", async () => {
  const page = await ext.context.newPage();
  await page.goto(attackerUrl());
  const result = await page.evaluate(
    (extId) => (window as unknown as { tryD6: (id: string) => Promise<string> }).tryD6(extId),
    ext.extensionId
  );
  // "threw" = chrome.runtime is not even exposed to this non-Beam origin;
  // "rejected" = exposed but no answer. Both prove the cookie never reaches it.
  expect(["rejected", "threw"]).toContain(result);
});
