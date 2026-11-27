---
domain: plan
iteration: 2
date: 2026-11-27
loop_status: CONTINUE
plan: conversion-apis_PLAN_27-11-26.md
---
# PVL iteration 002
- Input: CONDITIONAL — 0 FAIL, 6 CONCERN (N1–N6).
- Applied 6/6: click_ids from first click-id event (fbc_ts = its created_at, NULL default); named watermarks + lead predicate (FIRST_PARTY_PROVIDERS allow-list — values not yet enumerated); erasure + site-delete coverage (G13); Meta UA/event_source_url source + skipped_no_user_agent; AdConversionConfig reconciled (enabled_types dropped, HEX encoding in G12); scheduler/models touchpoints + 5a flag recheck.
- Validator 0/0; literal "Gate: PASS" outside contract: 0.
- Next: revalidate from V1 (must enumerate FIRST_PARTY_PROVIDERS from code).
