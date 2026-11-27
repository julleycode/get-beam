---
name: note:onsite-greeting-settings-ui
description: "Backlog — dashboard settings UI for the on-site greeting (v1 is API-only, U3)"
date: 27-11-26
feature: pixel
---
# On-site greeting — dashboard settings UI (backlog)

v1 (`active/onsite-greeting_27-11-26/`) ships owner settings via `PATCH /api/v1/sites/{site_id}`
only: `greeting_enabled` and `greeting_templates` (`{default: {text, cta_url}}`).

To build later:
- Toggle + template editor (text ≤200, `{company}` only, https CTA) on the site settings page.
- Snippet generator: add `data-greeting="on"` to the pixel tag when enabled.
- Preview using a sample company name. Blocked on the Clerk Playwright auth-harness gap for e2e.
- Optional v2: per-industry templates (U4), impression analytics.
