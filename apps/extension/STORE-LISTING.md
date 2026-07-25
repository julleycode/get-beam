# Chrome Web Store — listing & submission prep

Everything a human operator needs to submit this extension. Actual submission,
obtaining the real extension id, and store review are manual, days-long steps
outside the automated build (plan Step 9 note).

## Per-permission justification text (paste into the review form)

- **`cookies`** — "Reads the user's LinkedIn `li_at` session cookie, only when
  the user explicitly clicks Connect, so the user can authorize Beam to send
  LinkedIn outreach from their account. The cookie is handed only to the user's
  own Beam dashboard tab and is never stored or logged by the extension."
- **Host permission `*://*.linkedin.com/*`** — "Required to read the `li_at`
  cookie, which is HttpOnly and cannot be read by page JavaScript — host access
  to LinkedIn is the only way to obtain it."
- **Host permission for Beam origins (`https://getbeam.fyi/*`,
  `http://localhost:3000/*`)** — "Required to detect the user's own open Beam
  dashboard tab for the popup connect path, scoped only to Beam's own origins.
  This is used instead of the far broader `tabs` permission."
- **`externally_connectable` (Beam origins only)** — "Restricts cross-extension
  messaging so that only Beam's own dashboard pages can open a channel to this
  extension; no other site can request the LinkedIn session."

## Data-use disclosures (Chrome Web Store data form)

- Collects: **Authentication information** (the LinkedIn session cookie) and
  **User activity** is NOT collected.
- Usage: handed only to the user's own Beam dashboard tab; not sold; not used for
  anything unrelated to the single connect purpose.
- Not stored or logged by the extension (see `PRIVACY.md`).

## Privacy policy URL

`PRIVACY.md` (host its content at a public URL for the listing — e.g. alongside
Beam's existing privacy page at https://getbeam.fyi/beam/privacy.html, or a
dedicated extension-privacy page).

## Listing assets checklist

- [ ] 128×128 store icon (replace the placeholder `icons/icon-128.png`)
- [ ] At least one 1280×800 (or 640×400) screenshot/promo image
- [ ] Short description (≤132 chars), e.g. "Connect your LinkedIn session to Beam
      in one click — no manual cookie copying."
- [ ] Detailed description (reuse README "Architecture" + "Security posture")
- [ ] Category: **Productivity**
- [ ] Support / homepage URL: https://getbeam.fyi

## The one remaining code step after first upload (OI-4)

On first upload (even as a draft) the Chrome Web Store assigns the real
extension id. Replace `KNOWN_EXTENSION_ID = "PENDING_STORE_LISTING"` in BOTH:

- `apps/extension/src/known-origins.js`
- `apps/web/src/app/dashboard/social-accounts/page.tsx`

then rebuild the extension and redeploy the dashboard. Until then the D6 primary
channel cannot complete against the published extension (unpacked dev testing
uses the auto-assigned id, which the e2e harness discovers dynamically).

## Verified sign-off still required

CODE DONE ≠ VERIFIED. A human must confirm the end-to-end flow against a **real**
signed-in LinkedIn session in a real browser before this is considered verified —
the automated e2e uses a fake seeded cookie (plan Phase Completion Rules).
