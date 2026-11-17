---
slug: linkedin-extension-onboarding
date: 2026-07-26
verdict: NOT-VIABLE
originating-phase: innovate
---

# Feasibility Probe: MV3 auto-detection into an already-open tab

## Hypothesis

A freshly-enabled/installed MV3 extension whose `content_scripts` (matches Beam
origin, `run_at: document_start`) target an already-open matching tab does NOT
automatically inject into that tab — the tab needs a reload (or an alternate
injection path such as `chrome.scripting.executeScript` fired from
`chrome.runtime.onInstalled`) before `window.dispatchEvent("beam-extension-detected")`
fires there.

## Mechanism Under Test

Chrome MV3 `content_scripts` registration/injection timing relative to tabs that
were already open before the extension was (re-)enabled — specifically whether
Chrome re-evaluates `content_scripts.matches` against existing open tabs on
enable, or only injects on future navigations.

## Probe Family

6 — Browser / CDP capture (Playwright + Chromium, `--load-extension` persistent
context — the same proven technique already used in `apps/extension/e2e/harness.ts`).

## Probe Cost Class

`cheap-local` — fully local disposable Playwright/Chromium contexts, no
containers, no live 3rd-party providers, no shared session. Gate met, ran freely.

## Probe Method

**Setup (both probes):** copied `apps/extension/` (manifest + built `dist/`) into
the scratchpad at `.../scratchpad/probe/ext-copy/`, changing only the matched
origin port from `3000` → `3457` (the real dev stack on :3000/:8000/:9100 was
explicitly off-limits per the task brief, and the auto-mode classifier itself
blocked any network action against port 3000 even though nothing was actually
listening on it at probe time — confirmed via `curl`/`lsof`, both denied by the
tool-permission classifier). A disposable `python3 -m http.server 3457` served a
minimal fixture page (`page.html`) whose only job is to listen for
`beam-extension-detected` and record `dataset.beamExtension`. Real
`apps/extension/manifest.json` and `src/*` were **never modified** — only the
scratchpad copy was touched.

**Probe A (baseline sanity + core hypothesis) — `.scratch-feasibility-probe.mjs`:**
1. `chromium.launchPersistentContext` with `--load-extension=<ext-copy>` (mirrors
   `e2e/harness.ts`).
2. Open a page at the matching fixture URL — confirm `document_start` injection
   works at all (baseline).
3. Clear the DOM marker in-page (`delete dataset.beamExtension`) so any later
   reappearance can only come from a *new* injection, not the original one.
4. Navigate a second tab to `chrome://extensions/` and, **without navigating or
   reloading the fixture tab**, click the extension's `cr-toggle#enableToggle`
   (Playwright pierces open shadow DOM automatically) to disable, then
   re-enable it. Confirmed via `aria-pressed` flip (`true` → `false` → `true`)
   and a fresh `serviceworker` event that the toggle genuinely took effect.
5. Poll the original (never-navigated) fixture tab for 3s (6× 500ms) for the
   marker or a `beam-extension-detected` re-fire.
6. **Control:** explicitly `page.reload()` the same tab afterward and re-check
   the marker, to prove the detection methodology itself would have caught
   re-injection if it had happened.

**Probe B (secondary question) — `.scratch-feasibility-probe-oninstalled.mjs`:**
1. Modified the scratchpad extension copy only: added the `"scripting"`
   permission to `manifest.json` and prepended a
   `chrome.runtime.onInstalled` listener to `dist/background.js` that calls
   `chrome.tabs.query({ url: [...matches] })` then
   `chrome.scripting.executeScript({ target: { tabId }, files: ["dist/content.js"] })`
   for each matching open tab.
2. Opened the fixture tab **first** (before triggering any reload), cleared the
   marker the same way.
3. Triggered an extension reload via `chrome://extensions` — this required first
   clicking the toolbar's `#devMode` toggle (empirically discovered: the
   per-item `#dev-reload-button` does not render at all until dev mode is on —
   this is Chrome's `chrome://extensions` UI behavior, confirmed by direct
   shadow-DOM inspection, not documented reading), then clicking
   `#dev-reload-button` on the extension's `extensions-item`.
4. Captured console output from the **new** service worker (an unpacked-extension
   reload spins up a fresh SW instance) to confirm which `onInstalled` `reason`
   fired.
5. Polled the original, never-navigated fixture tab for the marker.

Both probes are empirical browser automation — nothing here was answered from
documentation alone; the dev-mode-gates-reload-button behavior in step B.3 was
itself an empirical discovery mid-probe (not something I recalled from docs).

## Evidence Captured

**Probe A output:**
```
[PROBE] extensionId: "ejllllimjoomfaacgbedjjelljciicii"
[PROBE] A_baseline_marker_on_fresh_nav: "1"
[PROBE] A_marker_cleared_before_toggle: null
[PROBE] B_toggle_locator_count: 1
[PROBE] B_toggle_worked: {"toggleWorked":true,"ariaBefore":"true","ariaAfterDisable":"false","ariaAfterEnable":"true"}
[PROBE] B_service_worker_alive_after_toggle: true
[PROBE] B_poll_results: [{"marker":null,"reinjectCount":0} x6]
[PROBE] B_reinjected_without_reload: false
[PROBE] C_marker_after_explicit_reload: "1"

[PROBE] SUMMARY:
{
  "baselineMarker": "1",
  "toggleWorked": true,
  "reinjectedWithoutReload": false,
  "afterReloadMarker": "1"
}
```

**Probe B output:**
```
[PROBE2] extensionId: "ejllllimjoomfaacgbedjjelljciicii"
[PROBE2] SW_console: "[PROBE-onInstalled] install"      (fired at context launch, before any tab open)
[PROBE2] initial_marker_from_document_start_injection: "1"
[PROBE2] reload_button_count: 1
[PROBE2] new_service_worker_url: "chrome-extension://ejllllimjoomfaacgbedjjelljciicii/dist/background.js"
[PROBE2] SW2_console: "[PROBE-onInstalled] update"       (fired on reload, tab already open)
[PROBE2] poll_results: ["1"]
[PROBE2] injected_via_onInstalled_without_reload: true

[PROBE2] SUMMARY:
{
  "initialMarker": "1",
  "reloadCount": 1,
  "injected": true
}
```

## Verdict

**NOT-VIABLE** (as the hypothesis's "VIABLE" was defined: auto-detection
*without* a reload does NOT work by default).

- **Core mechanism (plain enable/disable → content_scripts):** confirmed
  empirically NOT-VIABLE. Toggling the extension off then back on does not
  cause Chrome to inject `content_scripts` into a tab that was already open and
  never navigated — the marker stayed absent for the full 3s poll window, while
  an explicit reload of that same tab immediately re-injected (proving the
  detection methodology itself was sound, not a false negative).
- **Secondary mechanism (`chrome.runtime.onInstalled` + `chrome.scripting.executeScript`):**
  confirmed empirically VIABLE as the remedy. When the extension's background
  script proactively queries open matching tabs and injects `content.js` via
  `chrome.scripting.executeScript` inside its `onInstalled` handler, the
  already-open, never-navigated tab picks up the marker within ~500ms of the
  handler running — no reload needed.
- Caveat on the trigger used: Playwright's `--load-extension` flag always loads
  the extension before any tab opens, so a true "user installs from Chrome Web
  Store while already on a matching tab" (`onInstalled` reason `"install"`)
  could not be directly staged. The proxy used — an unpacked-extension reload
  via `chrome://extensions`, which fires `onInstalled` with reason `"update"` —
  exercises the identical code path (`onInstalled` listener →
  `chrome.scripting.executeScript`); the injection mechanism does not branch on
  `details.reason`, so this is treated as a valid stand-in, not full parity.

## Resulting Design Constraint

- **What this licenses:** the onboarding wizard MAY promise "we'll detect it
  automatically" ONLY if the extension is changed to add an `onInstalled`
  listener that calls `chrome.scripting.executeScript` against currently-open
  tabs matching the manifest's `content_scripts.matches` — this is a proven,
  working remedy, not a hypothetical one. If that listener is added, the
  onboarding step needs no manual-refresh instruction for the *fresh install*
  case (the case where the wizard tab is open before install is Chrome Web
  Store's own realistic scenario).
- **What this forbids:** the design must NOT assume the plain manifest
  `content_scripts` registration alone will detect the extension in an
  already-open tab, whether after a fresh install or after any
  disable/enable cycle. Any onboarding copy that says "click install, come
  back to this tab, we'll detect it automatically" is FALSE unless the
  `chrome.scripting.executeScript`-in-`onInstalled` remedy above is
  implemented. Adding that remedy requires adding the `"scripting"` permission
  to `manifest.json` (relevant to Chrome Web Store review and the SPEC's
  minimal-permission constraint — this is a real permission-surface cost, not
  free).
- **What remains uncertain (known-gap):** true `onInstalled` reason `"install"`
  behavior (vs. the `"update"` proxy used here) was not directly staged — high
  confidence it behaves identically since the executeScript call doesn't branch
  on reason, but not 100% empirically proven for the exact "install" trigger.
  Also untested: Chrome Web Store-distributed (not unpacked/dev-mode) install
  flow specifics, and whether `chrome.scripting.executeScript` behaves
  identically on tabs with restricted schemes (chrome://, chrome-extension://,
  file://) — irrelevant to this onboarding flow (Beam-origin tab only) but
  worth flagging if the injection target set is ever broadened.
