---
name: note:linkedin-onboarding-oninstalled-remedy
description: "Rejected-for-v1 remedy for the install-step reload: chrome.scripting.executeScript on onInstalled. FEASIBILITY-proven viable for fresh installs only; costs a new `scripting` permission."
date: 26-07-26
feature: campaigns-outreach
---

# Rejected remedy: `scripting` + `onInstalled` executeScript (onboarding D13)

Status: **REJECTED for v1**, documented for a possible future revisit. Not implemented.

## What it would do

On extension install, the service worker listens for `chrome.runtime.onInstalled` and calls
`chrome.scripting.executeScript` against any already-open Beam dashboard tab, injecting the
detection marker/event that a plain `content_scripts` declaration does NOT deliver to
already-open tabs.

## Why it was considered

The FEASIBILITY probe (`linkedin-extension-onboarding_FEASIBILITY_26-07-26.md`) empirically
proved that plain `content_scripts` do NOT inject into an already-open tab after install, nor
after a disable→enable cycle. That is why the shipped wizard's install step is reload-based
("I've installed it" → reload) rather than silently auto-detecting.

The `onInstalled` + `executeScript` approach was proven **VIABLE** by the same probe — for the
fresh-install case.

## Why it was rejected for v1

1. **It only fixes fresh installs.** The disable→enable case (and any other "extension became
   available in an already-open tab" case) still needs a reload, so the reload-based copy and the
   detection wiring would have to stay anyway. The remedy removes one click for one subset of
   users; it does not remove the mechanism.
2. **It costs a new `scripting` permission** on an extension that already reads a third-party auth
   cookie. That is a real store-review and user-trust cost for a click-count improvement, and it
   directly contradicts the plan's hard "zero new manifest permissions" constraint.

## If revisited

- Add `"scripting"` to `manifest.json` permissions (a permission-surface change → needs its own
  security review, not a drive-by edit).
- Add an `chrome.runtime.onInstalled` listener in `apps/extension/src/background.js` that finds
  Beam tabs via the existing `findBeamTab()` helper and injects the detection marker.
- Keep the reload-based path as the fallback — it is still the only thing that covers
  disable→enable.
- Update the Step 2 copy only if the marker delivery becomes reliable for BOTH cases; otherwise the
  "click I've installed it" instruction must stay (never promise silent detection).
