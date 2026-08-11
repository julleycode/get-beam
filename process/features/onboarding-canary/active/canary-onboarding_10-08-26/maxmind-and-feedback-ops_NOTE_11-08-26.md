---
name: report:maxmind-and-feedback-ops
description: Operator steps to activate MaxMind GeoLite2 (City + ASN) and read the identity_feedback counts
date: 11-08-26
metadata:
  node_type: memory
  type: report
  feature: onboarding-canary
  phase: phase-4-workstream-b
---

# Operator note — MaxMind activation + feedback counts

## TL;DR

Two things shipped dormant. MaxMind GeoLite2-City can displace ip-api.com for the
geo half of the location reveal, and an admin endpoint now reads the
`identity_feedback` table that nothing was reading. Neither changes behavior until
an operator acts.

---

## 1. Activate MaxMind — one key, TWO downloads, TWO config paths

The ASN rung of the network-label ladder is **dead in every environment today**:
`maxmind_asn_db_path` and `maxmind_license_key` both default to `""`
(`apps/api/config.py`) and no `.mmdb` exists anywhere on disk, so
`asn_lookup.lookup_asn()` returns `(None, None)` everywhere and the network label
falls all the way through to ip-api's `org`/`isp`. The **same free license key**
that enables the new City DB also fixes that rung — the network label improves as
a side effect of doing this.

Exact steps:

1. **Get the key.** Free account at <https://www.maxmind.com/en/geolite2/signup>,
   generate a license key. Set `MAXMIND_LICENSE_KEY=<key>` in the environment
   (Railway variables for prod).
2. **Download BOTH databases** (order does not matter):
   ```
   python -m scripts.download_geolite2_city   # -> data/GeoLite2-City.mmdb  (NEW)
   python -m scripts.download_geolite2_asn    # -> data/GeoLite2-ASN.mmdb   (existing)
   ```
3. **Set BOTH paths:**
   ```
   MAXMIND_CITY_DB_PATH=data/GeoLite2-City.mmdb   # NEW — enables the City rung
   MAXMIND_ASN_DB_PATH=data/GeoLite2-ASN.mmdb     # revives the dead ASN rung
   ```
4. **Restart the process.** The reader is opened lazily once per process and the
   `_load_attempted` guard means it is never retried after a failed open.
5. **Re-run weekly.** MaxMind refreshes GeoLite2 weekly; wire the two downloaders
   into deploy or a weekly cron or the data goes stale.

### Do NOT install City without ASN

City fills geo only — it carries no `isp`/`org`/`as` fields at all. A City hit
**skips the ip-api call entirely**, and ip-api is currently the *only* source of
org/isp. So City-alone silently drops the network line from the reveal (the ladder
correctly omits it rather than printing "Unknown ISP", but the line is gone).
Install both. This is written into the `maxmind_city_db_path` comment block in
`config.py` under KNOWN LIMITATIONS, and asserted by
`test_city_accuracy_radius_reaches_the_response`.

### What you get

- ip-api's 45-request/minute ceiling, plaintext HTTP, and non-commercial terms
  leave the now user-facing geo path (plan risk #6).
- A **real per-IP `accuracy_radius`** replaces the hard-coded 25km estimate in the
  reveal's accuracy circle. ip-api returns nothing comparable. `build_geo` uses the
  measured value when the City rung was the source, clamps 0 to 1km, and falls back
  to 25 otherwise.
- No `.mmdb` is committed to the repo, and none was downloaded during this work.

### Dormancy guarantee

With `maxmind_city_db_path` empty (the default, and what is deployed now),
`lookup_city` short-circuits before touching the filesystem and geo resolution is
byte-identical to today. Proven by `test_absent_db_fails_open`,
`test_load_is_attempted_once`, and the integration test
`test_city_db_rung_is_dormant_by_default` (fails the test if `geoip2.database.Reader`
is ever constructed while unconfigured).

---

## 2. Read the feedback counts

`GET /api/v1/onboarding/identity-feedback/stats?days=30` — **admin only**
(`require_admin`, the `request_logs` precedent), read-only, aggregate counts only.

```json
{
  "enabled": false,
  "window_days": 30,
  "total": 3,
  "with_note": 1,
  "by_reason": [
    {"reason": "not_me", "count": 0},
    {"reason": "vpn_or_proxy", "count": 1},
    {"reason": "wrong_city", "count": 2},
    {"reason": "wrong_network", "count": 0}
  ],
  "by_surface": [{"surface": "onboarding_canary", "count": 3}]
}
```

Notes:

- **No PII.** The `shown` JSONB (place names + rounded lat-lng) is never returned,
  not even sampled; `note` is free text so only its presence is counted. Asserted
  by `test_feedback_stats_aggregates_and_leaks_no_pii`, which greps the raw
  response body for the seeded city names, note text, and user id.
- **Not tenant-scoped**, unlike `/sites/{id}/ingest-health`: `site_id` is nullable
  because the canary runs *before* site creation, so most rows have no site.
- **Reports `enabled` instead of 404ing** when `location_reveal_enabled` is off — an
  operator still needs the history of a feature they just switched off, and the
  field separates "nobody complained" from "capture is off".
- All four reasons are **zero-filled**, so an untouched reason reads as a real `0`.
- No dashboard page was added. This endpoint plus this note is the surface.

### Named downstream consumer (so this does not go write-only again)

**Relay-detection precision metric.** Take the `vpn_or_proxy` count over a window
and cross-check those same reveals against
`company_resolver.check_ip_privacy` — users self-reporting "I'm on a VPN" on
sessions we did *not* flag as a relay are false negatives, and the ratio is a
running precision/recall number for relay detection that costs nothing in provider
spend. Secondary: `wrong_city` is the running error rate of IP geo, i.e. the single
number that says whether the MaxMind migration in §1 actually helped — capture it
for a couple of weeks *before* flipping `MAXMIND_CITY_DB_PATH` so there is a
baseline to compare against.

---

## Files

New: `apps/api/services/geoip_city.py`, `scripts/download_geolite2_city.py`,
`tests/unit/test_geoip_city.py`.
Modified: `apps/api/config.py`, `apps/api/services/geoip.py`,
`apps/api/services/onboarding_canary.py`, `apps/api/routers/onboarding.py`,
`tests/integration/test_onboarding_canary_api.py`.

No migrations. No changes to `apps/web/public/beam/*` or `apps/api/routers/demo.py`.
