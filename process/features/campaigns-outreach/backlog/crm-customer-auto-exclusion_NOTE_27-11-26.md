---
name: note:crm-customer-auto-exclusion
description: "Backlog: auto-populate site_exclusions (reason=customer) from connected CRM accounts"
date: 27-11-26
feature: campaigns-outreach
---
# CRM customer auto-exclusion — backlog NOTE

TL;DR: v1 company exclusion list is manual/CSV only (user decision 3, 27-11-26). Auto-sync of customer accounts from a connected CRM is deferred.

- Source plan: `active/company-exclusion-list_27-11-26/company-exclusion-list_PLAN_27-11-26.md`
- Idea: on CRM sync, upsert `site_exclusions(site_id, domain, reason='customer')` for closed-won account domains; keep a `source` column (add via migration) so manual rows are never overwritten or deleted by sync.
- Constraints to keep: reuse `validate_exclusion_domain` (freemail / public-suffix reject), log counts only, flag `company_exclusion_enabled`.
- Open: which CRM field marks "customer" per provider; deletion semantics when a CRM account churns.
