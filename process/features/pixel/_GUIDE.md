# pixel

<!-- Part of Beam -->

## Scope

The tracking pixel and event ingestion path: vanilla-JS tracker (zero deps, <5KB gzipped), event ingest API, consent mode (off/eu/all banner gating), GPC/DNT honoring, bot + datacenter + proxy/VPN filtering, server-set durable visitor id (`_rta_svid` HttpOnly cookie surviving Safari ITP), and the pixel install/verify onboarding flow (including the "send to my AI agent" install helper).

## Key Source Files

- `apps/pixel/src/tracker.js` — the pixel itself
- `apps/api/routers/events.py` — ingest endpoint (204s bot/UA-less traffic, tracking_enabled gate)
- `apps/api/services/bot_filter.py`, `asn_lookup` / datacenter + proxy detection (`BLOCK_DATACENTER_TRAFFIC`, `BLOCK_PROXY_VPN_TRAFFIC`, MaxMind GeoLite2-ASN offline DB)
- `apps/api/services/intent_score.py` + aggregation in `apps/api/tasks/aggregation_tasks.py`
- `apps/web/public/beam/onboarding-steps.js`, `onboarding.html` — install flow + platform snippets
- `apps/api/services/platform_detector.py` — Shopify/WordPress/Wix detection for install instructions
- ClickHouse events table (`CLICKHOUSE_*`), consent mode on `Site.consent_mode`

## Related Context

- `process/context/all-context.md` — Guardrail #3 (privacy: GPC/DNT → do_not_resolve sticky)
- `process/context/tests/all-tests.md` — `test_pixel*.py`, `test_events_ingest.py`, `test_bot_filter.py`, `test_consent_mode.py`; gotcha: `is_bot("")` is True

## Current Status

Status: stable — pixel + ingest + filtering shipped; onboarding install flow actively iterated.

## Folder Contents

```
process/features/pixel/
  active/       -- in-progress plans (each task in a {slug}_{date}/ folder)
  completed/    -- archived completed plans
  backlog/      -- deferred/future plans
```

All artifacts colocate inside each `{slug}_{date}/` task folder. Do NOT create `reports/` or `references/` sibling dirs.
