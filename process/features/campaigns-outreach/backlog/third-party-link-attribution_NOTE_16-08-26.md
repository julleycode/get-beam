---
name: note:third-party-link-attribution
description: "Third-party booking links carry no _bid/_tp by design (privacy guarantee); v2 attribution routes"
date: 16-08-26
metadata:
  node_type: memory
  type: report
  feature: campaigns-outreach
  phase: phase-1
---

# Third-party link attribution — a privacy guarantee, not a bug

**Status:** documented limitation, accepted. Raised by marketing-claims-gap Phase 1
(demo booking).

## What the limit is

`apps/api/services/link_decorator.py` decorates **same-host links only** — the
customer's own host and its subdomains. A campaign link to a third-party booking
host (Calendly, Cal.com) receives neither `_bid` nor `_tp`.

Consequence: a demo booking click cannot be attributed off the click itself.
`CampaignClick` never sees it, so `conversion_tracker` attribution falls back
entirely to the `same_visitor` branch, which needs a prior clicked touchpoint for
that visitor.

## Why this is deliberate

`_bid` is the recipient's email address, encrypted. Putting it on a third-party
URL hands an encrypted-PII token to a company Beam does not control and the site
owner did not authorize as a data processor. **This is a privacy guarantee, not a
link-parsing shortcoming.**

Locked by `tests/unit/test_link_decoration.py`:
`test_third_party_link_not_decorated` and
`test_booking_url_on_third_party_host_not_decorated` (both with a non-vacuous
same-host control in the same call).

## v1 route (shipped, Phase 1)

The customer points their Calendly/Cal.com confirmation redirect at their own
pixel'd thank-you page, then creates a "Demo booked" `ConversionGoal`
(`goal_type="url_match"`, `match_type="prefix"`, `pattern="/thanks"` — a **path**,
not a full URL).

## Candidate v2 routes — exactly two

1. **Provider webhook.** Calendly/Cal.com POST a booking event to the existing
   HMAC-verified outcomes endpoint (`apps/api/routers/outcomes.py:421`) with its
   rotatable secret. No token leaves Beam.
2. **Redirect-through-Beam interstitial.** The campaign link points at a Beam
   endpoint that records the click and 302s to the booking host, stripping the
   token before the redirect.

**"Decorate third-party links" is explicitly NOT a candidate fix.** It would leak
an encrypted-email token to Calendly/Cal.com and is rejected permanently, not
just for v1.

## Open residuals tracked here

- **Live-provider redirect chain (`needs-live-provider`).** No automated coverage
  proves a real Calendly/Cal.com redirect actually lands on the customer's pixel'd
  thank-you page and fires a conversion end to end. Requires a live provider
  account.
- **Same-tenant subdomain exception (accepted, documented).** A `booking_url` on a
  **subdomain of the customer's own host** WILL receive `_bid` — proven by
  `test_www_and_subdomain_match`. Accepted: the destination is same-tenant and
  owner-controlled. The site-settings helper text advises owners who object to use
  a path on their own site or a third-party booking host.
