import { chromium, type BrowserContext, type Worker } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

// Shared harness for the MV3 extension e2e specs.
//
// MV3 extensions load only into a persistent context launched with
// --load-extension (the OI-1-probed technique). We discover the auto-assigned
// extension id from the background service worker's URL, seed a fake li_at
// cookie directly into the browser's cookie jar (no linkedin.com navigation
// needed — OI-1 resolution), and point the fixture dashboard at that id via a
// query param (mirrors the real dashboard's fixed KNOWN_EXTENSION_ID).

const EXTENSION_ROOT = resolve(HERE, "..");
const FIXTURE_BASE = "http://localhost:3000";

export interface LoadedExtension {
  context: BrowserContext;
  extensionId: string;
  worker: Worker;
}

export async function launchExtension(): Promise<LoadedExtension> {
  const userDataDir = mkdtempSync(join(tmpdir(), "beam-ext-"));
  // MV3 extensions load only via a persistent context, and the OLD headless
  // mode cannot load extensions — use Chromium's new headless mode instead
  // (headless:false so Playwright doesn't add the legacy --headless flag; our
  // explicit --headless=new provides display-less new headless).
  const context = await chromium.launchPersistentContext(userDataDir, {
    headless: false,
    args: [
      "--headless=new",
      `--disable-extensions-except=${EXTENSION_ROOT}`,
      `--load-extension=${EXTENSION_ROOT}`,
    ],
  });

  // Wait for the background service worker to register, then read its id.
  let [worker] = context.serviceWorkers();
  if (!worker) worker = await context.waitForEvent("serviceworker");
  const extensionId = new URL(worker.url()).host;

  return { context, extensionId, worker };
}

/** Seed a fake li_at cookie directly into the cookie jar (OI-1 technique). */
export async function seedLinkedInCookie(
  context: BrowserContext,
  value = "AQEDA-fake-li_at-value"
): Promise<void> {
  await context.addCookies([
    {
      name: "li_at",
      value,
      domain: ".linkedin.com",
      path: "/",
      httpOnly: true,
      secure: true,
      sameSite: "None",
      expires: Math.floor(Date.now() / 1000) + 3600,
    },
  ]);
}

/** Fixture dashboard URL wired to the loaded extension's id. */
export function dashboardUrl(extensionId: string): string {
  return `${FIXTURE_BASE}/dashboard.html?extid=${extensionId}`;
}

export function attackerUrl(): string {
  // 127.0.0.1 is a DISTINCT match-host from "localhost" in Chrome match
  // patterns (which ignore the port entirely — localhost:3999 would still match
  // the manifest's localhost:3000). So the spoofed origin must differ by HOST,
  // not port. Served by the same static server on port 3999.
  return `http://127.0.0.1:3999/attacker.html`;
}
