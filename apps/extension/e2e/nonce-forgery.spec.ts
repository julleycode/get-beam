import { test, expect } from "@playwright/test";
import {
  launchExtension,
  seedLinkedInCookie,
  dashboardUrl,
  type LoadedExtension,
} from "./harness";

// AC6 (D7 path, D10/OI-3): a co-resident copy-cat extension runs in the same
// page context, so it can forge event.origin and knows the public
// source:"beam-extension" string. It cannot know the D6-registered nonce.
// The dashboard must reject a postMessage with a missing/wrong nonce.

let ext: LoadedExtension;

test.beforeEach(async () => {
  ext = await launchExtension();
  await seedLinkedInCookie(ext.context);
});

test.afterEach(async () => {
  await ext.context.close();
});

test("AC6: forged postMessage with wrong nonce is rejected", async () => {
  const page = await ext.context.newPage();
  await page.goto(dashboardUrl(ext.extensionId));

  // Simulate the co-resident attacker: correct origin + correct source string,
  // but a guessed/wrong nonce and an attacker cookie value.
  await page.evaluate(() => {
    window.postMessage(
      {
        source: "beam-extension",
        nonce: "attacker-guessed-nonce",
        ok: true,
        cookie: "attacker-value",
        userAgent: "attacker-ua",
      },
      window.location.origin
    );
  });

  // Give the handler a beat, then assert the dashboard never connected.
  await page.waitForTimeout(300);
  await expect(page.locator("#status")).not.toHaveText("connected");
});

test("AC6: forged postMessage with no source discriminator is ignored", async () => {
  const page = await ext.context.newPage();
  await page.goto(dashboardUrl(ext.extensionId));

  await page.evaluate(() => {
    window.postMessage(
      { ok: true, cookie: "attacker-value" },
      window.location.origin
    );
  });

  await page.waitForTimeout(300);
  await expect(page.locator("#status")).not.toHaveText("connected");
});
