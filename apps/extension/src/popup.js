// Popup (secondary trigger, plan D4/AC4). "Connect now" finds the open Beam
// dashboard tab and asks the worker to relay a connect response into it. If no
// Beam tab is open, it shows a clear "open your dashboard" message.
import { resolvePopupConnect } from "./connect-logic.js";
import { BEAM_ORIGIN_PATTERNS } from "./known-origins.js";

const btn = document.getElementById("connect");
const statusEl = document.getElementById("status");

function setStatus(text) {
  if (statusEl) statusEl.textContent = text;
}

btn?.addEventListener("click", async () => {
  btn.setAttribute("disabled", "true");
  setStatus("Connecting…");
  try {
    const result = await resolvePopupConnect(chrome, BEAM_ORIGIN_PATTERNS);
    if (result.status === "no-tab") {
      setStatus("Open your Beam dashboard tab, then click Connect now.");
    } else {
      setStatus("Sent to your Beam dashboard. Check the LinkedIn outreach card.");
    }
  } catch {
    setStatus("Something went wrong. Make sure your Beam dashboard tab is open.");
  } finally {
    btn.removeAttribute("disabled");
  }
});
