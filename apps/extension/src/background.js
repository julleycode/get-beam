// MV3 service worker (type: "module"). Owns cookie reads and both message
// channels. Never logs or stores the cookie / userAgent (plan AC8).
import {
  readLinkedInSession,
  checkLinkedInSignedIn,
  registerNonce,
  nonceForTab,
} from "./connect-logic.js";
import { MESSAGE_SOURCE } from "./known-origins.js";

// ── D6: primary channel — externally_connectable from a Beam-origin page ──
// Chrome only delivers onMessageExternal from pages whose origin is listed in
// manifest.externally_connectable.matches, and `sender` is verified by Chrome.
chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== "object") return false;

  // Register a per-page-load nonce so the D7 relay can be signed later (D10).
  // Only a genuine Beam-origin page can reach this handler (Chrome-verified).
  if (message.type === "register-nonce") {
    const tabId = sender && sender.tab ? sender.tab.id : undefined;
    registerNonce(tabId, message.nonce);
    return false; // no reply expected
  }

  if (message.type === "beam-connect-request") {
    readLinkedInSession(chrome).then((result) => sendResponse(result));
    return true; // async response
  }

  // Read-only signed-in probe for the onboarding wizard (onboarding plan D5).
  // Status only — the response shape has no cookie/userAgent field (AC5).
  //
  // Deliberately NO nonce on this leg, and that is not an oversight: the nonce
  // (D10) exists to protect the D7 window.postMessage RELAY, where event.origin
  // alone is forgeable by a co-resident extension. This probe is served ONLY on
  // onMessageExternal, which Chrome itself gates on
  // manifest.externally_connectable.matches with a Chrome-verified `sender` — a
  // control a co-resident extension cannot forge. There is no relay leg here, so
  // there is no gap for a nonce to close.
  if (message.type === "beam-session-check") {
    checkLinkedInSignedIn(chrome).then((result) => sendResponse(result));
    return true; // async response
  }

  return false;
});

// ── D7: popup relay — popup → this worker → content script → page ──
// The popup sends {type:"beam-connect-request", tabId} on the internal channel.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "beam-connect-request-popup") return false;

  const tabId = message.tabId;
  readLinkedInSession(chrome).then((result) => {
    // Relay into the target tab's content script, signed with the nonce that
    // page registered over the D6 channel. content.js only passes it through.
    const nonce = nonceForTab(tabId);
    chrome.tabs.sendMessage(tabId, {
      type: "beam-connect-response",
      source: MESSAGE_SOURCE,
      nonce,
      ...result,
    });
    sendResponse({ dispatched: true });
  });
  return true;
});
