import { test, expect } from "@playwright/test";
import {
  launchExtension,
  seedLinkedInCookie,
  dashboardUrl,
  type LoadedExtension,
} from "./harness";

// AC8: cookie/UA never client-stored. The extension requests no "storage"
// permission, so chrome.storage is undefined in its worker — and a full connect
// flow must not write anything anywhere. Static grep (over the diff) is the
// companion check (see plan Verification Evidence AC8 row).

let ext: LoadedExtension;

test.beforeEach(async () => {
  ext = await launchExtension();
  await seedLinkedInCookie(ext.context);
});

test.afterEach(async () => {
  await ext.context.close();
});

test("AC8: no chrome.storage is used during a full connect flow", async () => {
  const page = await ext.context.newPage();
  await page.goto(dashboardUrl(ext.extensionId));
  await page.click("#connect");
  await expect(page.locator("#status")).toHaveText("connected");

  // The worker never requested the storage permission → chrome.storage is
  // undefined; assert it stayed that way (nothing was written).
  const storageState = await ext.worker.evaluate(async () => {
    // @ts-expect-error chrome typing not available in the worker eval scope
    if (typeof chrome === "undefined" || !chrome.storage) return "absent";
    // @ts-expect-error chrome typing not available in the worker eval scope
    const local = await chrome.storage.local.get(null);
    // @ts-expect-error chrome typing not available in the worker eval scope
    const session = chrome.storage.session
      ? // @ts-expect-error chrome typing not available in the worker eval scope
        await chrome.storage.session.get(null)
      : {};
    return JSON.stringify({ local, session });
  });

  expect(
    storageState === "absent" || storageState === '{"local":{},"session":{}}'
  ).toBeTruthy();
});
