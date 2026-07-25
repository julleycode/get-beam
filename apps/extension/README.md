# Beam — LinkedIn Outreach Connect (browser extension)

MV3 browser extension (Chrome/Edge) that replaces the manual DevTools `li_at`
cookie-copy step with a one-click connect into the user's open Beam dashboard
tab. It is a **dumb pipe**: it reads the LinkedIn session cookie and hands it to
the Beam dashboard over a locally-scoped, nonce-verified browser message
channel. It never calls the Beam backend directly and never holds a Beam login.

The dashboard then calls the existing, unchanged
`POST /api/v1/social/accounts/linkedin/outreach-connect` endpoint. The manual
cookie-paste form on the dashboard remains as a permanent fallback.

## Architecture (how the cookie moves)

1. `background.js` (service worker) reads the `li_at` cookie via `chrome.cookies`
   (needs `host_permissions` for `*.linkedin.com` — the cookie is HttpOnly and
   cannot be read by page JS).
2. **Primary channel (D6):** the dashboard page calls
   `chrome.runtime.sendMessage(KNOWN_EXTENSION_ID, {type:"beam-connect-request"})`
   over `externally_connectable` (Chrome verifies the sender). The worker replies
   with the cookie + User-Agent on that same channel.
3. **Secondary channel (D7):** the extension popup finds the open Beam tab
   (`chrome.tabs.query`, populated via `host_permissions` — no `tabs` permission),
   and relays through `content.js` → one `window.postMessage` into the page. The
   page verifies **origin + source + a per-page-load nonce** (the nonce is
   registered only over the sender-verified D6 channel), so a co-resident
   copy-cat extension cannot forge a response.

## Security posture

- Cookie/User-Agent are **never logged and never stored** (no `console.*`,
  `localStorage`, or `chrome.storage`; the extension requests no `storage`
  permission).
- Minimal permissions: `cookies` + `host_permissions` (`*.linkedin.com` +
  Beam origins) + `externally_connectable` (Beam origins). No `<all_urls>`, no
  `tabs`, no `scripting`.
- The cookie only ever reaches a Beam origin — enforced structurally by
  `externally_connectable.matches` (D6) and `content_scripts.matches` (D7).

## Develop / build

```bash
cd apps/extension
npm install
npm run build        # bundles src/ → dist/ via esbuild
```

## Load unpacked (dev)

1. Build (above): `npm install && npm run build`.
2. Open `chrome://extensions`, enable **Developer mode**.
3. **Load unpacked** → select `apps/extension/` (the folder with `manifest.json`).
4. Confirm the extension card shows **ID: `ejllllimjoomfaacgbedjjelljciicii`**. This
   fixed id is pinned by the manifest `key` field, so it's identical on every
   machine — and `KNOWN_EXTENSION_ID` (here **and** in the dashboard mirror
   `apps/web/src/app/dashboard/social-accounts/page.tsx`) is already set to match it.
   No per-load patching needed.
5. Run the dashboard against a **Beam origin the manifest allows** — `localhost:3000`
   (`cd apps/web && npm run dev`) or `getbeam.fyi`. The in-page button uses the
   primary `externally_connectable` channel, which requires the origin to be in the
   manifest's `externally_connectable`/`host_permissions` — a random localhost port
   or other host will NOT work.
6. Sign into `linkedin.com` in the **same browser** (the extension reads its `li_at`
   cookie).
7. Go to **Social Accounts → LinkedIn outreach** → click **Connect with extension**
   (or the toolbar popup's **Connect now**).

Debug: `chrome://extensions` → the extension's **service worker** link opens the
background console (cookie read); F12 on the dashboard tab shows the page-side
message + nonce exchange.

> The manifest `key` (public) is committed so the dev id is stable. Its matching
> private key lives at `.keys/dev-key.pem` (gitignored) — only needed if you ever
> self-pack a `.crx`; not needed for unpacked loading or Chrome Web Store upload.

## Test

```bash
npm test         # node:test unit tests (cookie-read + popup logic; AC3, AC4)
npm run test:e2e # Playwright: persistent-context MV3 load (AC1, AC5, AC6, AC8, AC10)
```

The e2e suite loads the built `dist/` — run `npm run build` first. It is
local-only (not CI-wired), matching the existing `apps/pixel/e2e` precedent.

## Chrome Web Store submission (Step 9 — manual, days-long)

See `STORE-LISTING.md` for the per-permission justification text, listing
metadata checklist, and the privacy policy pointer (`PRIVACY.md`).

The Chrome Web Store assigns its **own** extension id on first upload, regardless
of the manifest `key`. At submission:
1. Remove the `key` field from `manifest.json` (the store manages the id).
2. Replace the dev id `ejllllimjoomfaacgbedjjelljciicii` in `src/known-origins.js`
   **and** the dashboard mirror (`apps/web/src/app/dashboard/social-accounts/page.tsx`)
   with the store-assigned id (plan OI-4).

The bundled icons (`icons/icon-{16,32,48,128}.png`) are the real Beam brand mark —
generated from `icons/icon.svg` (source of truth: the Beam beam/sparkle on the
pink brand gradient, matching `apps/web/src/app/icon.svg`). To regenerate after
editing the SVG, rasterize it to the four sizes with any SVG→PNG tool.
