---
name: note:closed-won-lookalikes-live-provider-gates
description: "Known-gap residuals for closed-won-lookalikes: live Meta/Google/HubSpot/Pipedrive/Salesforce legs (needs-live-provider)"
date: 27-11-26
feature: ads-audiences
---
# Closed-won lookalikes — live provider gates (known-gap)

All provider legs ran in mock mode only. Before `closed_won_lookalikes_enabled` is flipped on, run these with operator double opt-in:

- KG-L Meta: LOOKALIKE create from a processed seed in a sandbox ad account (v25 `lookalike_spec.country`); confirm seed-not-ready error text is surfaced.
- KG-L Google: `lookalikeUserList` create from a Customer Match seed; confirm DUPLICATE_LOOKALIKE body shape; Demand Gen attachment.
- KG-L HubSpot: pipelines API stage metadata, deals search re-window past 10k, v4 associations, reconnect flow for pre-deals tokens.
- KG-L Pipedrive: `deals?status=won` expanded `person_id.email` shape.
- KG-SF Salesforce: orgs without OpportunityContactRoles return no emails.
- KG-HS: `hs_is_closed_won` internal property not used (pipelines path is primary).
- Merge check: company-exclusion module signatures (`load_exclusions`, `match_excluded(exclusions, domain=...)`, `.reason`) once the sibling plan lands.
- Poll cursor is `max(updated_at) - 1 day` per connection (no cursor column); revisit if polling volume grows.
