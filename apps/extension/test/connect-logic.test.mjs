// Unit tests for the pure connect logic. Node's built-in test runner, no
// browser needed. Proves AC3 (not-signed-in) and AC4 (no Beam tab open).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  readLinkedInSession,
  checkLinkedInSignedIn,
  findBeamTab,
  resolvePopupConnect,
  registerNonce,
  nonceForTab,
  _resetNonces,
} from "../src/connect-logic.js";

function fakeChrome(overrides = {}) {
  return {
    cookies: {
      get: async () => null,
      ...overrides.cookies,
    },
    tabs: {
      query: async () => [],
      ...overrides.tabs,
    },
    runtime: {
      sendMessage: async () => ({ dispatched: true }),
      ...overrides.runtime,
    },
  };
}

// ── AC3: not signed into LinkedIn ──
test("AC3: cookies.get null → not_signed_in, never a silent empty send", async () => {
  const chrome = fakeChrome({ cookies: { get: async () => null } });
  const result = await readLinkedInSession(chrome);
  assert.equal(result.ok, false);
  assert.equal(result.reason, "not_signed_in");
  assert.equal("cookie" in result, false);
});

test("AC3: cookie present with empty value → not_signed_in", async () => {
  const chrome = fakeChrome({ cookies: { get: async () => ({ value: "" }) } });
  const result = await readLinkedInSession(chrome);
  assert.equal(result.ok, false);
  assert.equal(result.reason, "not_signed_in");
});

test("AC3: cookies.get throws → cookie_read_failed, no crash", async () => {
  const chrome = fakeChrome({
    cookies: {
      get: async () => {
        throw new Error("boom");
      },
    },
  });
  const result = await readLinkedInSession(chrome);
  assert.equal(result.ok, false);
  assert.equal(result.reason, "cookie_read_failed");
});

test("signed in → ok with cookie value", async () => {
  const chrome = fakeChrome({
    cookies: { get: async () => ({ value: "AQEDA-fake-li_at" }) },
  });
  const result = await readLinkedInSession(chrome);
  assert.equal(result.ok, true);
  assert.equal(result.cookie, "AQEDA-fake-li_at");
  assert.equal(typeof result.userAgent, "string");
});

// ── AC4: no matching Beam tab open ──
test("AC4: no Beam tab → resolvePopupConnect returns no-tab, dispatches nothing", async () => {
  let dispatched = false;
  const chrome = fakeChrome({
    tabs: { query: async () => [] },
    runtime: {
      sendMessage: async () => {
        dispatched = true;
      },
    },
  });
  const result = await resolvePopupConnect(chrome, ["https://getbeam.fyi/*"]);
  assert.equal(result.status, "no-tab");
  assert.equal(dispatched, false);
});

test("AC4: Beam tab present → dispatched with that tab id", async () => {
  const chrome = fakeChrome({
    tabs: { query: async () => [{ id: 42, url: "https://getbeam.fyi/dashboard" }] },
  });
  const result = await resolvePopupConnect(chrome, ["https://getbeam.fyi/*"]);
  assert.equal(result.status, "dispatched");
  assert.equal(result.tabId, 42);
});

test("findBeamTab ignores tabs without a numeric id", async () => {
  const chrome = fakeChrome({ tabs: { query: async () => [{ url: "x" }] } });
  assert.equal(await findBeamTab(chrome, ["*"]), null);
});

// ── Onboarding AC5: read-only signed-in probe never returns the cookie ──
test("AC5: checkLinkedInSignedIn never returns a cookie key (signed in)", async () => {
  const chrome = fakeChrome({
    cookies: { get: async () => ({ value: "AQEDA-fake-li_at" }) },
  });
  const result = await checkLinkedInSignedIn(chrome);
  assert.deepEqual(result, { signedIn: true });
  // Explicit key-presence assertions, not just falsy checks.
  assert.equal("cookie" in result, false);
  assert.equal("userAgent" in result, false);
  assert.deepEqual(Object.keys(result), ["signedIn"]);
});

test("AC5: checkLinkedInSignedIn cookie null → not_signed_in, no cookie key", async () => {
  const chrome = fakeChrome({ cookies: { get: async () => null } });
  const result = await checkLinkedInSignedIn(chrome);
  assert.deepEqual(result, { signedIn: false, reason: "not_signed_in" });
  assert.equal("cookie" in result, false);
  assert.equal("userAgent" in result, false);
});

test("AC5: checkLinkedInSignedIn empty cookie value → not_signed_in", async () => {
  const chrome = fakeChrome({ cookies: { get: async () => ({ value: "" }) } });
  const result = await checkLinkedInSignedIn(chrome);
  assert.deepEqual(result, { signedIn: false, reason: "not_signed_in" });
});

test("AC5: checkLinkedInSignedIn cookies.get throws → cookie_read_failed, no cookie key", async () => {
  const chrome = fakeChrome({
    cookies: {
      get: async () => {
        throw new Error("boom");
      },
    },
  });
  const result = await checkLinkedInSignedIn(chrome);
  assert.deepEqual(result, { signedIn: false, reason: "cookie_read_failed" });
  assert.equal("cookie" in result, false);
});

// ── D10 nonce registry ──
test("nonce registry: register then look up by tab id", () => {
  _resetNonces();
  registerNonce(7, "nonce-abc");
  assert.equal(nonceForTab(7), "nonce-abc");
  assert.equal(nonceForTab(8), undefined);
});

test("nonce registry: rejects non-string / missing values", () => {
  _resetNonces();
  registerNonce(undefined, "n");
  registerNonce(1, "");
  assert.equal(nonceForTab(1), undefined);
});
