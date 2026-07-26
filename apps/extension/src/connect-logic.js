// Pure, chrome-injected logic for the connect flow. Kept free of top-level
// chrome.* access so it can be unit-tested in node with a fake chrome object
// (see test/connect-logic.test.mjs — proves AC3 and AC4).
//
// SECURITY: never log or store the cookie / userAgent anywhere (plan AC8).

import {
  LINKEDIN_COOKIE_URL,
  LINKEDIN_COOKIE_NAME,
} from "./known-origins.js";

/**
 * Single shared cookie-read + not-signed-in detection path (onboarding plan D6).
 * BOTH readLinkedInSession() (full connect, returns the cookie) and
 * checkLinkedInSignedIn() (read-only probe, never returns the cookie) call this
 * — there is deliberately no duplicated "not signed in" branch between them.
 * @param {typeof chrome} chromeApi
 * @returns {Promise<{ok: true, value: string} | {ok: false, reason: "not_signed_in" | "cookie_read_failed"}>}
 */
async function readLinkedInCookieValue(chromeApi) {
  let cookie;
  try {
    cookie = await chromeApi.cookies.get({
      url: LINKEDIN_COOKIE_URL,
      name: LINKEDIN_COOKIE_NAME,
    });
  } catch {
    return { ok: false, reason: "cookie_read_failed" };
  }

  // Not signed in → cookies.get resolves null. Never send a silent empty
  // cookie (plan AC3).
  if (!cookie || !cookie.value) {
    return { ok: false, reason: "not_signed_in" };
  }

  return { ok: true, value: cookie.value };
}

/**
 * Read the LinkedIn li_at session cookie via the injected chrome API.
 * @param {typeof chrome} chromeApi
 * @returns {Promise<{ok: true, cookie: string, userAgent: string} | {ok: false, reason: string}>}
 */
export async function readLinkedInSession(chromeApi) {
  const read = await readLinkedInCookieValue(chromeApi);
  if (!read.ok) {
    return { ok: false, reason: read.reason };
  }

  // Service-worker global scope exposes navigator.userAgent (self.navigator).
  const userAgent =
    (typeof self !== "undefined" && self.navigator && self.navigator.userAgent) ||
    "";

  return { ok: true, cookie: read.value, userAgent };
}

/**
 * Read-only "is the user signed into LinkedIn?" probe (onboarding plan D5).
 *
 * SECURITY (AC5): the returned object structurally has NO `cookie` and NO
 * `userAgent` field on either branch — status only. The onboarding wizard needs
 * to know whether to show "sign into LinkedIn" without triggering a full
 * connect, and a boolean is the least it can be told.
 *
 * @param {typeof chrome} chromeApi
 * @returns {Promise<{signedIn: true} | {signedIn: false, reason: "not_signed_in" | "cookie_read_failed"}>}
 */
export async function checkLinkedInSignedIn(chromeApi) {
  const read = await readLinkedInCookieValue(chromeApi);
  if (!read.ok) {
    return { signedIn: false, reason: read.reason };
  }
  return { signedIn: true };
}

/**
 * Find the first open Beam dashboard tab matching the given URL patterns.
 * Requires host_permissions for those origins so url/title are populated
 * WITHOUT the broad "tabs" permission (plan OI-2).
 * @param {typeof chrome} chromeApi
 * @param {string[]} originPatterns
 * @returns {Promise<{id: number} | null>}
 */
export async function findBeamTab(chromeApi, originPatterns) {
  const tabs = await chromeApi.tabs.query({ url: originPatterns });
  const tab = Array.isArray(tabs) ? tabs.find((t) => typeof t.id === "number") : null;
  return tab ? { id: tab.id } : null;
}

/**
 * Popup "Connect now" action. Finds a Beam tab; if none is open, returns a
 * prompt to open the dashboard (plan AC4) and dispatches nothing. If found,
 * asks the worker to relay a connect response into that tab.
 * @param {typeof chrome} chromeApi
 * @param {string[]} originPatterns
 * @returns {Promise<{status: "no-tab"} | {status: "dispatched", tabId: number}>}
 */
export async function resolvePopupConnect(chromeApi, originPatterns) {
  const tab = await findBeamTab(chromeApi, originPatterns);
  if (!tab) {
    return { status: "no-tab" };
  }
  await chromeApi.runtime.sendMessage({
    type: "beam-connect-request-popup",
    tabId: tab.id,
  });
  return { status: "dispatched", tabId: tab.id };
}

// In-memory nonce registry, keyed by initiating tab id. Populated only via the
// Chrome-sender-verified D6 channel (register-nonce), never from page-readable
// surfaces (plan D10). Not persisted — lives only for the service worker's life.
const nonceByTabId = new Map();

/** Register a page-minted nonce for a tab (D6 channel, sender-verified). */
export function registerNonce(tabId, nonce) {
  if (typeof tabId === "number" && typeof nonce === "string" && nonce) {
    nonceByTabId.set(tabId, nonce);
  }
}

/** Look up the nonce previously registered for a tab (used to sign D7 relay). */
export function nonceForTab(tabId) {
  return nonceByTabId.get(tabId);
}

/** Test-only reset of the nonce registry. */
export function _resetNonces() {
  nonceByTabId.clear();
}
