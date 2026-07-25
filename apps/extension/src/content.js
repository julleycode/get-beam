// Injected only on Beam origins (manifest content_scripts.matches), at
// document_start. Two jobs: (a) advertise the extension's presence; (b) relay
// the D7 popup-triggered response into page JS via a single postMessage hop.
import { MESSAGE_SOURCE } from "./known-origins.js";

// (a) Detection marker (plan D5). DOM attribute is the first-paint fallback;
// the CustomEvent covers the case where the page's listener mounts after us.
document.documentElement.dataset.beamExtension = "1";
window.dispatchEvent(new CustomEvent("beam-extension-detected"));

// (b) Popup relay: background.js → content script → page. content.js NEVER
// generates or inspects the nonce — it only forwards what background attached
// (background→content is a same-extension Chrome-enforced channel; content→page
// is the only page-readable leg). Target origin is this page's own origin, so
// the postMessage cannot leak cross-origin (plan D7 / Security Checklist item 1).
chrome.runtime.onMessage.addListener((message) => {
  if (!message || message.type !== "beam-connect-response") return;
  window.postMessage(
    {
      source: MESSAGE_SOURCE,
      nonce: message.nonce,
      ok: message.ok,
      cookie: message.cookie,
      userAgent: message.userAgent,
      reason: message.reason,
    },
    window.location.origin
  );
});
