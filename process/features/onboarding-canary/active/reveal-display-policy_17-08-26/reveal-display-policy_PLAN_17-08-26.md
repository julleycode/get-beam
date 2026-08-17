---
name: plan:reveal-display-policy
description: "Reveal display policy v2 — map only when the city is certain; country card otherwise; no-claim on fail. Server-decided display_mode across both reveal surfaces."
date: 17-08-26
feature: onboarding-canary
---

# Reveal Display Policy v2 — map only when we are sure

**Date**: 17-08-26
**Status**: PLANNED (not validated, not executed)
**Complexity**: COMPLEX
**Feature**: onboarding-canary
**Flag**: `location_reveal_enabled` (existing, default OFF) — no new flag, no migration

## Overview

**TL;DR** The reveal currently draws a map (and a city name) whenever coordinates exist, including when the two geo providers disagree, when no second opinion exists at all, and when the address is a mobile carrier whose centroid is routinely a different city. This plan makes the **server** pick one of three display modes — `map` / `country` / `none` — strips anything the chosen mode may not claim *before it is sent*, and teaches all three clients (React reveal, public vanilla funnel, country card) to render exactly what they were given. Complexity: **COMPLEX**. No migration. Everything stays behind `location_reveal_enabled`.

---

## Decision Record (LOCKED by user 17-08-26 — do not re-litigate)

Copied verbatim from the locking session. EXECUTE must implement these as written; a checklist item that contradicts a decision here is a plan bug, not a licence to choose.

**D1 — Map + pin + city name** ONLY when ALL of: crosscheck confidence == `high` AND network kind is user-owned (isp/company/network — NOT relay/datacenter) AND NOT mobile-carrier connection.

**D2 — Country card (no map)** when geo usable but any of:
- confidence == `low` (2 providers disagree)
- confidence == `unverified` (no second opinion — user chose STRICT: no map even though city likely right)
- mobile-carrier ASN detected (even when confidence high — the mobile-agree centroid trap)
- VPN/datacenter/relay kind (show exit-node country WITH disclaimer copy "(your vpn's location, probably not yours)" — user explicitly chose to keep a country card here rather than no-claim)

**D3 — No-claim copy** when geo is None / Null Island / provider fail: plain-language line, no location claim.

**D4 — Country certainty hardening.** Country must be ~100% right when shown. `_lookup_second` currently returns lat/lon/city only; add a second-provider **country_code** comparison. If the two providers disagree on COUNTRY → treat as the no-claim case (do **not** show a country card).

**D5 — Mobile detection: build NOW.** New helper `is_mobile_carrier()` — static mobile-carrier ASN set + org-string regex fallback (mobile/cellular/wireless/telecom-mobile brands). Do **NOT** mutate `classify_org_kind` taxonomy; ip-org fusion consumers depend on it.

**D6 — Copy register.** lowercase, playful-honest, NO tech jargon. Banned substrings in any user-facing string: `IP`, `geolocation`, `database`, `ASN`, `crosscheck`. Wording may be refined; register may not.

**D7 — Both surfaces.** The policy applies to the onboarding canary AND the public demo. `routers/demo.py:430` states "Most reveals happen here" — a divergence would leave the larger half unfixed.

**D8 — Server decides.** The server emits `display_mode` and sends nothing the mode may not print (mirror of the existing "a name that must not be sent" rule in `build_geo`'s docstring). Clients consume it; the only client-side degrade is tile failure.

### Accepted residual risk (explicit, user-acknowledged)

D4 targets **city** certainty. When no second opinion is obtainable (ipinfo down / keyless ceiling hit), the country comes from the primary provider alone. Country-level accuracy from a single provider is ~98-99%. Blocking the country card on a missing second opinion would gut the entire fallback path — which is the path D2 routes the *majority* of traffic to. **Decision: allow the country card when the second-provider country is unknown; block it only on a positive disagreement.** Encoded as `country_agreed: bool | None` where `None` = unknown = allowed.

---

## Facts established this session (cite, do not re-derive)

| Fact | Evidence |
|---|---|
| Both surfaces already share the assembly functions | `routers/onboarding.py:106` (`crosscheck_geo`), `:108` (`build_geo`), `:109` (`build_network`) and `routers/demo.py:415-420` both call the same three with identical arguments **(anchors corrected by PVL gap A — the earlier `107-109` was off by one)** |
| `build_geo` already strips city+region server-side on `low` | `services/onboarding_canary.py` — `confidence` set to `high`/`unverified`/`low`; `low` blanks `city`/`region` and widens `accuracy_km` to the measured disagreement |
| `build_network` yields kind ∈ company/isp/relay/datacenter/network | `services/onboarding_canary.py:201+`, via `classify_org_kind` + `is_privacy_relay_ip`, with a fabrication guard and rung-5 omission |
| `_lookup_second` returns `(lat, lon, city)` — **no country** | `services/geoip_crosscheck.py:153+`; cached Redis JSON is `{"loc", "city"}` under `geoipx:` |
| Mock mode always agrees | `crosscheck_geo` short-circuits to `CrossCheck(checked=True, agreed=True, distance_km=0.0, second_city="Mountain View")` under `mock_external_apis` |
| Mock geo fixture | `_mock_geo` → `country_code="US"`, `city="Mountain View"`, `isp="Mock ISP"`, `org="Mock Org"`, `as_str="AS15169 Mock AS"` |
| `ip_family` logged on every reveal, and stamped server-side into feedback | `onboarding.py:121`, `onboarding.py:175`, `demo.py:432`, `demo.py:488`; stats surface at `onboarding.py:317` |
| `RevealMode` is `"map" \| "text" \| "skip"`, pure and unit-tested | `apps/web/src/lib/canary-reveal-mode.ts`, `canary-reveal-mode.test.ts` |
| Fabrication guard + copy live client-side too | `apps/web/src/lib/canary-format.ts` — `formatNetwork`, `formatConfidenceNote`, `NOT_THE_USER` |
| **THIRD client exists** | `apps/web/public/beam/onboarding-steps.js` — duplicates `formatConfidenceNote` at :149, calls `/api/v1/demo/canary` at :396, renders the map card at :450-467, posts `shown.confidence` at :539. The public funnel is plain JS and does not import from `src/lib`. |
| Frontend unit runner exists | `apps/web/vitest.config.ts`, `npm run test` → `vitest run`, `environment: node`, `src/**/*.test.ts`; 12 existing `src/lib/*.test.ts` files |
| Existing crosscheck tests | `tests/unit/test_geoip_crosscheck.py` (33 pass) |
| Docker IS available | `process/context/tests/all-tests.md` — `which docker` lies; detect with `lsof -nP -iTCP -sTCP:LISTEN \| grep -E '5433\|6379'`. "environment-blocked" is **not** a valid known-gap category in this repo |

---

## Touchpoints

**Backend — changed**
- `apps/api/services/geoip_crosscheck.py` — `_lookup_second` returns country; `CrossCheck` gains `second_country` + `country_agreed`
- `apps/api/services/onboarding_canary.py` — new pure `choose_display_mode()`; `build_geo` honours the mode (strip / null)
- `apps/api/routers/onboarding.py` — call the decider, emit `display_mode`, stamp `shown["display_mode"]`
- `apps/api/routers/demo.py` — identical changes (D7 parity)

**Backend — new**
- `apps/api/services/mobile_carrier.py` — `is_mobile_carrier(ip, geo) -> bool`

**Frontend — changed**
- `apps/web/src/lib/canary-format.ts` — `CanaryResponse.display_mode`, new copy functions
- `apps/web/src/lib/canary-reveal-mode.ts` — `RevealMode` gains `"country"`; consume `display_mode`
- `apps/web/src/components/onboarding/canary-reveal.tsx` — branch on the new mode
- `apps/web/src/components/onboarding/canary-listen.tsx` — **(added by PVL gap I)** `:89` calls `chooseRevealMode(data) !== "skip"` to decide whether a reveal happens at all; the `RevealMode` widening makes `"country"` a new non-skip value it must accept
- `apps/web/src/components/onboarding/canary-map.tsx` — **(added by PVL F2)** dereferences `geo.lat`/`geo.lng`/`geo.accuracy_km` at :92, :167-168, :192, :221; its prop must be narrowed to a required-coords type once `CanaryGeo` widens
- `apps/web/src/components/onboarding/onboarding-flow.tsx` — **(added by PVL F2)** `:248-249` computes `Math.round(geo.lat * 100) / 100`; in `country` mode `geo` is truthy but `geo.lat` is `undefined` → `NaN` → silently posts `lat: null`
- `apps/web/src/lib/onboarding-script.ts` — **(added by PVL gap D)** the React reveal's scripted copy; `REVEAL_GEO_ONLY` at `:87` carries a user-facing D6-banned `IP` string that the AC-12 scan never sees
- `apps/web/public/beam/onboarding-steps.js` — same policy in the vanilla funnel, **including its OWN duplicated `hasUsableGeo` at :179-185, `chooseRevealMode` at :187-195, and the `wantsMap` computation at :459** (PVL F1; anchors corrected by gap A — `:461` is the `${wantsMap ? …}` interpolation, not the computation)

**Frontend — new**
- `apps/web/src/components/onboarding/canary-country-card.tsx`

**Tests — changed**: `tests/unit/test_geoip_crosscheck.py`, `apps/web/src/lib/canary-reveal-mode.test.ts`, `apps/web/src/lib/canary-format.test.ts`, `tests/integration/test_onboarding_canary_api.py`, `apps/web/e2e/onboarding-canary.spec.ts` — **(added by PVL F4)** already exists, is **not** skip-guarded, mocks the canary API at the network layer, and runs under the `chromium` project; the `RevealMode` widening and the low-confidence render removal land inside its assertions
**Tests — new**: `tests/unit/test_mobile_carrier.py`, `tests/unit/test_reveal_display_policy.py`

**Read-only context**: `apps/api/services/company_resolver.py`, `apps/api/services/geoip.py`, `apps/api/services/ip_resolution.py`, `apps/api/models/identity_feedback.py`

### Must NOT change (regression fence)

`apps/pixel/src/tracker.js` · `apps/api/services/identity_resolver.py` · `is_emailable_identity` · `classify_org_kind` (D5) · `resolve_geoip` frozen 2-tuple signature · `apps/api/routers/events.py` ingest path · any Alembic migration.

---

## Public Contracts

### 1. `display_mode` — new top-level response key (both `/api/v1/onboarding/canary` and `/api/v1/demo/canary`)

```
"display_mode": "map" | "country" | "none"
```

Additive. Old clients that ignore it behave as today. New clients treat it as authoritative.

**Server-side stripping, by mode** (the whole point — a claim the mode may not make is never serialised):

| `display_mode` | `geo` payload | `network` payload |
|---|---|---|
| `map` | full: `lat,lng,accuracy_km,city,region,country_code,confidence` | unchanged |
| `country` | `country_code` + `confidence` + optional `disagree_km` **only**; `city`/`region` = `""`; `lat`/`lng`/`accuracy_km` **omitted** | unchanged (the VPN disclaimer needs `kind`) |
| `none` | `null` | unchanged (a network label is not a location claim) |

`reason` (existing, optional) gains one value: `country_disagreement`.

### 2. `CrossCheck` (internal, duck-typed by `build_geo`)

Gains `second_country: str` (`""` = unknown) and `country_agreed: bool | None` (`None` = unknown). Existing attributes and `to_dict()` keys are preserved and additive. **(PVL gap A — corrected.)** Both new fields carry defaults, so they are non-breaking: the file holds exactly ONE equality assertion (`test_geoip_crosscheck.py:110`, `assert result == CrossCheck()`) and it is green at 33 passed today. No pre-emptive assertion churn is budgeted; update it only if a run proves otherwise.

### 3. `is_mobile_carrier(ip: str, geo) -> bool` (new, pure-ish)

Duck-types `geo` (reads `isp`/`org`/`as_str` only). Never raises. `False` on any doubt — a false negative shows a map that might be wrong; a false positive downgrades a correct map to a country card. Both are survivable; the module documents that we prefer the downgrade and therefore matches liberally.

### 4. `identity_feedback.shown["display_mode"]`

Server-owned, stamped alongside the existing `shown["ip_family"]`. `shown` is JSONB — **no migration**. Lets `by_ip_family` style segmentation extend to "which card did the complainer actually see", which is the only way to tell a wrong-city report on a map from one on a country card.

### 5. `RevealMode` (frontend)

`"map" | "text" | "country" | "skip"` — a widened union. Every `switch`/`if` over `RevealMode` must be re-checked; TS exhaustiveness will not catch a non-exhaustive `if` chain.

---

## Design

### Decision table (the single source of truth for both server and tests)

Inputs: `geo_usable` (coords present, not Null Island), `confidence` ∈ {high, unverified, low}, `kind` ∈ {company, isp, network, relay, datacenter, cdn, None}, `mobile` ∈ {T, F}, `country_agreed` ∈ {True, False, None}.

| # | geo_usable | country_agreed | confidence | kind | mobile | → display_mode | copy |
|---|---|---|---|---|---|---|---|
| 1 | T | True/None | high | isp/company/network | F | **map** | city + pin |
| 2 | T | True/None | high | isp/company/network | T | **country** | mobile-uncertain |
| 3 | T | True/None | high | relay/datacenter/cdn | any | **country** | vpn disclaimer |
| 4 | T | True/None | unverified | isp/company/network | F | **country** | country-only |
| 5 | T | True/None | unverified | relay/datacenter/cdn | any | **country** | vpn disclaimer |
| 6 | T | True/None | low | any | any | **country** | country-only |
| 7 | T | **False** | any | any | any | **none** | lookup-fail / no-claim |
| 8 | F (None / Null Island / provider fail) | any | any | any | any | **none** | lookup-fail |
| 9 | T | True/None | high | **None** (rung-5 empty) | F | **map** | city + pin |

**`cdn` dead-branch note (PVL N4):** `cdn` can never appear in a response — `build_network` re-maps `cdn`→`relay` at `onboarding_canary.py:239-240`. The `{relay, datacenter, cdn}` set in this table and in step 21a therefore carries a permanently dead branch; it is harmless defensive breadth and is deliberately kept.

Precedence, evaluated top-down (this ordering is normative):
1. `not geo_usable` → `none`
2. `country_agreed is False` → `none` (reason `country_disagreement`) — **(PVL gap E)** this rule is **implemented in `build_geo` (step 13), NOT in `choose_display_mode`**: `build_geo` returns `None`, which reaches `choose_display_mode` as `not geo_usable`. The routers discriminate row 7 from row 8 via `reason` (step 14). The rule is listed here because it is normative policy, not because the decider evaluates it.
3. `kind in {relay, datacenter, cdn}` → `country` (vpn copy) — checked **before** mobile, so a VPN on a phone reads as a VPN
4. `mobile` → `country` (mobile copy)
5. `confidence != "high"` → `country` (country-only copy)
6. else → `map`

**Row 9 accepted known-gap (PVL gap I):** `build_network` returns `None` when every label rung is empty — and it returns early **before** `is_privacy_relay_ip` is consulted. A label-less privacy relay therefore reaches row 9 with `kind = None` and renders a **map**. Accepted: the rung-5 empty case is rare, and blocking on it would suppress the map for every unlabelled ordinary ISP. Recorded here rather than fixed; revisit if the real-network matrix surfaces it.

Row 9 note: an empty network line (`build_network` rung 5) does **not** block the map. D1's "network kind is user-owned" excludes relay/datacenter, and "no label at all" is not a hosting claim.

### Where the decision lives

`choose_display_mode(geo_payload, network_payload, *, mobile) -> str` — **pure**, in `apps/api/services/onboarding_canary.py`, immediately after `build_geo`. Pure so the 9-row table above is an exhaustive unit test rather than something only observable by holding a VPN.

`build_geo` gains a keyword-only `country_agreed: bool | None = None` and applies the **stripping** for the chosen mode. Rationale for keeping strip inside `build_geo` rather than in the routers: the existing `low` strip already lives there and the docstring's rule ("a name that must not be shown must not be sent") is a property of that function. Two strip sites would rot apart.

Router shape, identical in both files:

```python
mobile = is_mobile_carrier(ip, geo_raw) if geo_raw is not None else False
geo = build_geo(geo_raw, crosscheck=cross, country_agreed=getattr(cross, "country_agreed", None))
network = build_network(ip, geo_raw) if geo_raw is not None else None
display_mode = choose_display_mode(geo, network, mobile=mobile)
geo = apply_display_mode(geo, display_mode)   # strip / null, pure
```

`apply_display_mode` is a second pure helper rather than a flag on `build_geo` — `build_geo` cannot see `network`, and threading network into it would give one function two unrelated jobs.

### Country hardening (D4)

- `_point_from` also reads `data.get("country")` (ipinfo returns a 2-letter code) → `(lat, lon, city, country)`.
- Redis JSON gains `"country"`. **No key-namespace bump**: a pre-existing cache line simply has no `country`, `.get("country","")` yields `""` = unknown = `country_agreed: None` = allowed (per the accepted residual). Bumping `geoipx:` would throw away a live 24h cache to buy nothing.
- `_L1` in-memory tuple widens to 4 — internal, but `_store`/`_L1` typing must be updated together or mypy-style drift creeps in.
- Comparison is case-insensitive, whitespace-stripped, and **only** made when both sides are non-empty. Primary empty → `None`. Second empty → `None`.
- Mock mode returns `second_country="US"`, `country_agreed=True` — matching `_mock_geo.country_code="US"`.

### Mobile detection (D5)

New `apps/api/services/mobile_carrier.py`. **Placement justification:** not in `company_resolver.py` (D5 explicitly freezes that taxonomy — ip-org fusion, `resolve_org_domain`, and the `org_kind` classification table consume it); not inline in `onboarding_canary.py` (a ~60-line ASN table plus regexes would bury the reveal-assembly logic, and both routers plus two test files want it in isolation). A single-purpose module keeps the blast radius at one new file, is independently unit-testable, and is discoverable enough that no one is tempted to widen `classify_org_kind` later.

- **Zero imports from `company_resolver`.** Enforce with a unit test asserting the module source contains no `company_resolver` import (same shape as the roster-precision AST purity gate).
- Static ASN set — minimum coverage: VN Viettel, Mobifone, Vinaphone, FPT-mobile; US T-Mobile, Verizon Wireless, AT&T Mobility. ASN parsed from `geo.as_str` via a local `AS(\d+)` regex (do **not** import `company_resolver._ASN_RE` — that would be an import).
- Regex fallback over `org`/`isp`: generic tokens `mobile`, `cellular`, `wireless`, `gsm`, `lte`, `4g`, `5g`, plus this **explicit brand-token list (PVL gap I — no longer left as "plus explicit brand tokens")**: `viettel`, `mobifone`, `vinaphone`, `t-mobile`, `verizon wireless`, `at&t mobility`. Word-boundary anchored — `"T-Mobile"` must hit and `"Mobilezone Datacenter GmbH"` must not be a silent false positive we never notice (fixture it either way and record the chosen behaviour).
- **Required fixture (PVL gap I): `"FPT Telecom"` → NOT mobile.** FPT Telecom is FPT's **fixed-line** arm; only `FPT-mobile` belongs in the ASN set. A bare `telecom` token would sweep in every fixed-line ISP on earth, so `telecom` is **not** a generic token — mobile brand matching is by explicit brand only. This fixture is the guard on that boundary, and it documents the plan's downgrade-bias limit: the bias prefers a false-positive downgrade, but not one broad enough to downgrade all of fixed-line.
- Never raises: the whole body is wrapped so a malformed `geo` returns `False`.

### Copy (D6 register)

In `canary-format.ts` (and mirrored verbatim in `onboarding-steps.js`, which cannot import it):

| Case | String |
|---|---|
| country card, uncertain (rows 4, 6) | `your internet provider only tells me the country, not the city — so that's all i'll claim.` |
| country card, mobile (**row 2 ONLY** — see note) | `you're on a phone connection — those move around, so i'll only claim the country.` |
| country card, vpn/relay (rows 3, 5) | `you're browsing through something that hides your location — this is where it says it is, probably not where you are.` |
| no-claim (rows 7, 8) | `i couldn't read anything from your connection this time. it happens.` |

**Mobile-copy reconciliation (PVL gap E — resolves a contradiction between the copy table and the decision table).** The `mobile` flag is **never serialised** to the client; the only client-visible signature of a mobile downgrade is `display_mode == "country"` **with `confidence == "high"`** (nothing else routes a high-confidence connection to a country card except relay/datacenter, which the client distinguishes via `network.kind`). Therefore the mobile-specific note applies to the **high × mobile row (row 2) only**. A `low`- or `unverified`-confidence mobile connection is indistinguishable client-side from any other low/unverified connection and renders the **standard country-card uncertain note** (rows 4, 6). `formatCountryCardNote` (step 21) selects on `network.kind` + `geo.confidence` and must encode exactly this: relay/datacenter/cdn → vpn copy; else `confidence === "high"` → mobile copy; else → uncertain copy.

Banned-substring test (D6) runs over every exported copy string in `canary-format.ts`.

**Scan semantics (PVL F3 — normative, do not infer):**
- `IP` and `ASN` — **case-SENSITIVE whole-token** match (word-boundary anchored). A case-insensitive scan would false-positive on ordinary words (`equipment`, `description`); a case-sensitive substring scan would false-positive on `ISP`-adjacent casing. Only the bare uppercase acronym as its own token is banned.
- `geolocation`, `database`, `crosscheck` — **case-INSENSITIVE substring** match.
- After the F3 deletion above there is no retained string in `canary-format.ts` that trips this scan.

### Removed behaviour

The wide-circle map for `confidence: "low"` is **GONE** — row 6 routes to the country card, so `low` is unreachable on the map path.

**`formatConfidenceNote` deletion — CORRECTED PREMISE (PVL gap C; the cycle-1 "it is dead code" reasoning was FALSE and is struck).**

The true reason to delete it: **the render block at `canary-reveal.tsx:107-111` is NOT mode-gated** — it sits outside the `mode === "map"` branch, beside the `mode === "text"` branch — and **`country` mode still ships `confidence`** (plus optional `disagree_km`) per this plan's own payload table and step 12. Left in place, the function would fire **under the new country card** and print the D6-banned `"the IP databases disagree about your city…"` — re-leaking the exact city hedge that `country` mode exists to suppress. **The deletion is load-bearing, not cleanup.** An execute-agent must calibrate thoroughness to that: this is a correctness edit on a live path, not tidying of dead code.

**EXACT deletion sites (delete all of these, nothing more):**

| File | Site | What |
|---|---|---|
| `apps/web/src/lib/canary-format.ts` | `:163-170` | the `formatConfidenceNote` function itself (and its JSDoc block above it) |
| `apps/web/src/lib/canary-format.test.ts` | `:138-176` | its whole `describe` block (see step 33) |
| `apps/web/src/components/onboarding/canary-reveal.tsx` | `:6` | the `formatConfidenceNote` import |
| `apps/web/src/components/onboarding/canary-reveal.tsx` | `:47` | the `const confidenceNote = …` call |
| `apps/web/src/components/onboarding/canary-reveal.tsx` | `:107-111` | the JSX block **and** its `data-testid="canary-confidence-note"` (a deliberate testid contract removal) |
| `apps/web/public/beam/onboarding-steps.js` | **`:144-154` ONLY** | the mirrored comment + `formatConfidenceNote` function |
| `apps/web/public/beam/onboarding-steps.js` | `:450` | the `const confidenceNote = formatConfidenceNote(res.geo);` call site |
| `apps/web/public/beam/onboarding-steps.js` | **`:467`** | the `${confidenceNote ? '<p class="ob-map-note">' + _esc(confidenceNote) + '</p>' : ''}` interpolation |

**DO NOT TOUCH `onboarding-steps.js:155-160`.** That range is the **head of `formatNetwork`**, including its fabrication guard (`if (!label) return null;` — omit the line rather than print "Unknown ISP") and the relay/datacenter copy `switch`. The cycle-1 range `:144-160` was wrong and would have deleted a privacy guard. The correct function range is `:144-154`.

**Why `:467` is not optional:** `onboarding-steps.js` is untyped vanilla JS **with no compiler**. Deleting the `:450` const while leaving the `:467` interpolation throws a `ReferenceError` at reveal time and takes down the **entire public reveal card** — on the client this plan names its highest-risk surface, and no lint or type gate would catch it. After editing the file, run `grep -n confidenceNote apps/web/public/beam/onboarding-steps.js` and require **zero** hits.

The country card prints `formatCountryCardNote` (step 21) instead — no "shortened variant" of the old string is introduced.

**Nothing is deleted from `canary-map.tsx`** (PVL gap A) — the accuracy circle at `:167-168` is REQUIRED in `map` mode. Note: `build_geo`'s server-side radius widening on `low` becomes dead in practice (radius is not sent in `country` mode) — leave the server code, it is the correct behaviour if the policy ever loosens, and deleting it would re-open the "client hides it" hole.

---

## Blast Radius

| Metric | Value |
|---|---|
| Files changed | **14** (4 backend changed, 1 backend new, **8** frontend changed, 1 frontend new) — 10 → 12 (PVL F2 added `canary-map.tsx` + `onboarding-flow.tsx`) → **14** (PVL gap D added `src/lib/onboarding-script.ts`; PVL gap I added `canary-listen.tsx`) |
| Test files touched | **7** (2 new backend unit, 2 changed frontend unit, 1 changed backend unit, 1 changed integration, **1 changed e2e** — `apps/web/e2e/onboarding-canary.spec.ts`, added by PVL F4) |
| Packages | `apps/api`, `apps/web` |
| Migrations | **none** (`shown` is JSONB) |
| Flags | none new — all behind existing `location_reveal_enabled` (default OFF) |
| Risk class | **user-facing claim correctness + privacy-adjacent display**. Not auth/billing/schema. No new external provider call. |
| Cross-tenant surface | none — `fetch_journey` site scoping untouched |

**Highest-risk item:** the public `onboarding-steps.js` client. It is vanilla JS with duplicated logic and only Playwright coverage, and it serves the majority of reveals (`demo.py:430`). A correct server + an unupdated public client = the policy is silently unenforced where it matters most.

---

## Implementation Checklist

**Section A — country hardening (backend)**

1. `apps/api/services/geoip_crosscheck.py`: widen `_point_from` to return `(lat, lon, city, country)`, reading `data.get("country")`, upper-cased, `""` when absent/non-str.
2. Same file: widen `_L1` type and `_store` signature to the 4-tuple; update the two `_L1` read sites.
3. Same file: persist `"country"` in the `geoipx:` Redis JSON in `_lookup_second`; read it back with `.get("country","")` so pre-existing cache lines stay valid (no namespace bump).
4. Same file: add `second_country: str = ""` and `country_agreed: bool | None = None` to `CrossCheck.__slots__`, `__init__`, and `to_dict()`.
5. Same file: **update the 3-tuple unpack at `geoip_crosscheck.py:130`** (`second_lat, second_lon, second_city = second`) to the 4-tuple `second_lat, second_lon, second_city, second_country = second` — this is the exact site that raises `ValueError` the moment step 1 widens `_point_from`, and it is the only unpack site (PVL C1).
5a. Same file: in `crosscheck_geo`, compute `country_agreed` — case-insensitive strip compare of `getattr(primary,"country_code","")` vs `second_country`; `None` when either side is empty. Log `geo_country_disagreement` (`ip=ip[:8]`, both codes) when `False`.
6. Same file: mock branch returns `second_country="US"`, `country_agreed=True`.

**Section B — mobile detection (backend, new)**

7. Create `apps/api/services/mobile_carrier.py` with module docstring stating the D5 placement rationale and the "prefer false-positive downgrade" bias.
8. Add `_MOBILE_ASNS: frozenset[int]` covering Viettel, Mobifone, Vinaphone, FPT-mobile, T-Mobile US, Verizon Wireless, AT&T Mobility — each entry commented with the carrier name.
9. Add `_MOBILE_RE` (word-boundary, case-insensitive) over the token list in §Design.
10. Implement `is_mobile_carrier(ip: str, geo) -> bool`: parse ASN from `geo.as_str` with a local regex → ASN-set hit; else regex over `org` then `isp`. Whole body in `try/except Exception: return False`.

**Section C — display-mode decision (backend)**

11. `apps/api/services/onboarding_canary.py`: add `choose_display_mode(geo, network, *, mobile) -> str`, implementing the §Design precedence list top-down, with the 9-row table reproduced in the docstring.
12. Same file: add `apply_display_mode(geo, mode) -> dict | None` — `map` passthrough; `country` returns `{country_code, confidence}` (+ `disagree_km` when present), `city`/`region` as `""`, `lat`/`lng`/`accuracy_km` **absent**; `none` returns `None`.
13. Same file: extend `build_geo(..., country_agreed: bool | None = None)` and return `None` when `country_agreed is False` (row 7). Keep the existing `low` strip and radius widening untouched.

**Section D — routers (both surfaces, D7)**

14. `apps/api/routers/onboarding.py`: import `is_mobile_carrier`, `choose_display_mode`, `apply_display_mode`; compute `mobile`; pass `country_agreed=getattr(cross,"country_agreed",None)` into `build_geo`; compute + apply the mode; add `"display_mode": display_mode` to `result`; set `result["reason"]` per this **normative precedence** (PVL C3 — the two `None`-geo cases are otherwise indistinguishable without consulting `cross`):
    1. `geo_raw is None` → `reason = "provider_unavailable"` (existing behaviour at `onboarding.py:96` / `demo.py:408`, unchanged — `demo.py` anchor corrected by gap A).
    2. else `geo is None and getattr(cross, "country_agreed", None) is False` → `reason = "country_disagreement"`.
    3. else leave `reason` unset.
    Identical code in both routers — no divergence.
15. Same file: extend the `onboarding_canary` structlog line with `display_mode=display_mode` and `mobile=mobile`. Keep `ip=ip[:8]` and `ip_family=` exactly as-is.
16. Same file, `onboarding_identity_feedback`: stamp `shown["display_mode"]` server-side beside the existing `shown["ip_family"]`. Accept the client's value only as an overwritten input — never trust it.
17. `apps/api/routers/demo.py`: apply steps 14-16 verbatim to `demo_canary` / `demo_identity_feedback` (keep `_ip_family` alias usage and `ANONYMOUS_USER_ID`). No divergence.

**Section E — mock-mode landing check (guards the local demo)**

18. Verify that under `MOCK_EXTERNAL_APIS=true` the fixture lands in **row 1 (map)**: `confidence=high` (mock crosscheck agrees), `country_agreed=True`, `mobile=False`, and `build_network` kind ∈ {isp, company, network}.

    **E1 empirical result — PRE-ANSWERED, recorded inline (PVL gap A; re-derived twice, cycles 1 and 2). This step is a confirmation, not an open question:**

    | Input | Result |
    |---|---|
    | `_mock_geo.as_str` | `"AS15169 Mock AS"` |
    | `classify_org_kind("AS15169 Mock AS")` | `eyeball` |
    | `build_network(...).kind` | `company` |
    | `choose_display_mode(...)` | **row 1 → `map`** |

    The mock therefore already lands on the map path. Nothing needs to change for it to do so.
19. **Do NOT modify `apps/api/services/geoip.py::_mock_geo`.** (PVL gap A — the cycle-1 licence to "change only the mock fixture strings" is **struck**; it was a pure hazard, since step 18 is pre-answered as passing.) `_mock_geo` is not in this plan's blast radius and mutating it would silently change every other mock-mode test's fixture. If a local run disagrees with the E1 table above: re-derive by calling `classify_org_kind` directly on the fixture's `as_str`, record the discrepancy in the phase report, and **stop** — do not edit any fixture, and do not relax `classify_org_kind` or the policy.

**Section F — frontend shared lib**

20. `apps/web/src/lib/canary-format.ts`: add `export type DisplayMode = "map" | "country" | "none"` and `display_mode?: DisplayMode` to `CanaryResponse` (optional — an older server omits it).
20a. **(PVL F2 — the type currently lies.)** Same file: make `lat`, `lng`, and `accuracy_km` **optional** on `CanaryGeo` (`canary-format.ts:28-30`) — `country` mode omits all three, so the current required declaration is false. Widen the type FIRST, then run `cd apps/web && npm run lint` to let the compiler enumerate every real dereference site rather than grepping by hand. Fix every site the compiler names; do **not** silence with `!` or `as`.
20b. **(PVL F2.)** `apps/web/src/components/onboarding/canary-map.tsx`: narrow its `geo` prop from `CanaryGeo` to a **required-coords** type (e.g. `CanaryGeo & { lat: number; lng: number; accuracy_km: number }`), so a `country`-mode payload cannot reach Leaflet with `undefined` coordinates at :92, :167-168, :192, :221. The map is only rendered in `map` mode, so the narrowing is satisfiable at the call site; guard at the call site if the compiler disagrees.
20c. **(PVL F2.)** `apps/web/src/components/onboarding/onboarding-flow.tsx:248-249`: the `shown` builder computes `geo ? Math.round(geo.lat * 100) / 100 : null`. In `country` mode `geo` is truthy and `geo.lat` is `undefined` → `NaN` → `JSON.stringify` silently serialises `lat: null`. Make the coordinate fields coordinate-optional-safe (`typeof geo?.lat === "number" ? ... : null`). While here, add `display_mode` to the React `shown` builder for parity with funnel step 27 (PVL N7).
21. Same file: add `formatCountryName(countryCode)` (flag emoji + name; a small local map is fine — do not add a dependency for it) and `formatCountryCardNote(response): string` returning the D6 string for mobile / vpn-relay / uncertain, chosen from `network.kind` + `geo.confidence`.
21a. **(PVL gap E — note-selection is mode-derived, not mobile-derived.)** `formatCountryCardNote` selects in this exact order: (1) `network.kind ∈ {relay, datacenter, cdn}` → vpn copy; (2) else `geo.confidence === "high"` → mobile copy (a high-confidence country card can only mean a mobile downgrade); (3) else → uncertain copy. `mobile` is never sent to the client, so it must not appear in any client-side condition.
22. `apps/web/src/lib/canary-reveal-mode.ts`: widen `RevealMode` with `"country"`. `chooseRevealMode` consumes `response.display_mode` first: `"none"` → `"skip"` unless pages or a network label exist (then `"text"` with no location claim); `"country"` → `"country"` regardless of `tileState` (no tiles are used); `"map"` → `"map"`, degrading to `"text"` when `tileState === "failed"`. When `display_mode` is absent, fall back to today's logic verbatim.
22a. **(PVL gap F — React no-claim parity, D7.)** The funnel renders the D6 no-claim line for `display_mode: "none"` (step 25); React must render the **same line** on the none-mode-with-journey path. In `canary-reveal.tsx`, when the server sent `display_mode === "none"` but pages or a network label exist (mode resolves to `"text"`), render the D6 no-claim string `i couldn't read anything from your connection this time. it happens.` above the page list. The existing skip line at `onboarding-flow.tsx:269` may remain for the **true-skip** path (no data at all) — it is a different case. Without this step the funnel makes an honest no-claim statement and React silently shows a bare page list, a D7 divergence.
23. Create `apps/web/src/components/onboarding/canary-country-card.tsx` — flag + country name + one D6 line. No Leaflet import, no tile dependency, no `TileState` prop.
24. `apps/web/src/components/onboarding/canary-reveal.tsx`: add the `"country"` branch rendering the new card. **The ONLY deletion in this file is the `confidenceNote` JSX block at `:107-111`** (including its `data-testid="canary-confidence-note"` — a deliberate testid contract removal), plus the now-unused `formatConfidenceNote` import at `:6` and its call at `:47`. Keep the page list and network line rendering in every non-`skip` mode. Preserve every other existing `data-testid`; add `data-testid="canary-country-card"`.

    **(PVL gap G — suppress the legacy place row in `country` mode.)** `canary-reveal.tsx:46` computes `const place = formatPlace(response.geo)` and `:66` renders it behind a `◎` glyph. In `country` mode `geo.city`/`geo.region` are `""` but `country_code` survives, so `formatPlace` returns a bare `"US"` — which would render **beside** the new country card, making the same country claim twice in two visual registers. Hide the place row entirely when `display_mode === "country"`; the country card is the sole country claim in that mode.

    **(PVL gap A — explicit do-not-touch.)** **NOTHING is deleted from `apps/web/src/components/onboarding/canary-map.tsx`.** Earlier plan text said "remove the `low`-confidence wide-circle map rendering" from `canary-reveal.tsx`; that file contains no circle at all. The accuracy circle lives at **`canary-map.tsx:167-168`**, is driven by `accuracy_km`, and is **REQUIRED** in `map` mode — it is the honesty affordance that replaced the deleted IP-estimate caption. Deleting it would be a silent user-visible regression that **no gate catches** (`vitest` runs `environment: node` and cannot render; no e2e asserts the circle). `low` simply becomes unreachable on the map path under row 6 — no circle code is removed anywhere.

**Section G — public vanilla funnel (D7, highest risk)**

25a. **(PVL F1 — do this FIRST, before step 25.)** `apps/web/public/beam/onboarding-steps.js`: the funnel has its **own** duplicated `chooseRevealMode(res, tilesFailed)` and `hasUsableGeo` at **:187-195**, and `wantsMap` is computed from it at **:461**. Rewrite that local `chooseRevealMode` to consume `res.display_mode` FIRST, with the **identical precedence** used in `canary-reveal-mode.ts` step 22: `"none"` → `"skip"` unless pages or a network label exist (then `"text"` with no location claim); `"country"` → `"country"` regardless of tile state; `"map"` → `"map"`, degrading to `"text"` when tiles failed; `display_mode` absent → fall back to today's geo-presence logic verbatim. Update the `wantsMap` computation at **:459** to read the new mode (`:461` is only the `${wantsMap ? …}` interpolation — it needs no edit beyond the country/none branches added in step 25). Add a cross-reference comment in **both** this function and `canary-reveal-mode.ts` noting they must stay in sync (the funnel cannot import from `src/`). Without this, the funnel would render country-card markup while `wantsMap` still came from the OLD geo-presence logic — the exact "correct server + unenforced client" failure named as this plan's highest risk.
25. `apps/web/public/beam/onboarding-steps.js`: read `res.display_mode` at the reveal step (~:450) and branch — map card as today for `"map"`; a country card (same markup shape, no Leaflet init) for `"country"`; the no-claim line for `"none"`. Keep `_esc()` on every interpolated value.
25b. **(PVL gap G — same double-claim as the React side.)** The funnel's legacy place row is the `${place ? … ◎ …}` interpolation at **`:463`**, fed by `const place = formatPlace(res.geo)` at `:449`. In `country` mode `formatPlace` returns a bare country code, so the row would render beside the new country card and claim the country twice. Suppress the place row when `res.display_mode === "country"`. Mirror the React suppression in step 24 exactly.
26. Same file: mirror the D6 copy strings verbatim from `canary-format.ts` with a cross-reference comment in **both** files noting they must stay in sync (the funnel cannot import from `src/`).
26a. **(PVL gap C — the funnel half of the `formatConfidenceNote` deletion.)** Delete, in this file and by these exact ranges: **`:144-154` ONLY** (the mirrored comment + the `formatConfidenceNote` function), the `:450` call site, and the **`:467` `${confidenceNote ? …}` interpolation**. **Do NOT touch `:155-160`** — that is the head of `formatNetwork`, including its fabrication guard and the relay/datacenter copy `switch`. Leaving `:467` behind after deleting `:450` is a runtime `ReferenceError` that kills the whole public reveal card, and this file has no compiler to catch it. **Exit condition: `grep -n confidenceNote apps/web/public/beam/onboarding-steps.js` returns zero hits.**
27. Same file (~:539): include `display_mode: res.display_mode || null` in the `shown` object posted to `/api/v1/demo/identity-feedback` (the server overwrites it — this is for parity of the client-side payload shape only).
27a. **(PVL N3 — funnel coordinate guard, mirrors step 20c.)** Same file, `:532-533`: the feedback POST computes `Math.round(geo.lat * 100) / 100` unguarded. In `country` mode `geo` is truthy and `geo.lat` is `undefined` → `NaN` → `JSON.stringify` emits `null`. Guard it the same way step 20c guards the byte-identical React expression (`typeof geo?.lat === "number" ? ... : null`) so the two clients stay symmetric. The emitted value is already correct either way — this is parity, not a bug fix; if the guard is skipped, record explicitly in the phase report that **NaN→null is accepted and deliberately unmirrored**.

**Section H — tests** (see Verification Evidence for the gate matrix)

**Execute-agent instructions carried into this section (transcribed verbatim from the Validate Contract, PVL cycle 3 — normative, not advisory):**

- **E-11 (H1) — baseline-first for the integration gate.** Run `.venv/bin/python -m pytest tests/integration/test_onboarding_canary_api.py -q` **once before extending it** and record the verbatim result in the phase report. Do **not** compare the full lane against any written-down number — re-measure in-session.
- **E-12 (H1) — shared-DB contention is not a regression.** `asyncpg UniqueViolationError ... pg_type_typname_nsp_index` / `CREATE TYPE ... AS ENUM` errors against `:5433` mean **a concurrent session is running the integration lane on the shared dev Postgres**. Confirm with `ps aux | grep [p]ytest` **before attributing any integration error to this change**; wait for the other run to finish and re-run. This is contention, never a regression, and **never grounds to punt a gate**. Observed live at contract time — three consecutive runs of the canary file degraded 7 → 9 → 12 errors while a sibling session (PID 23769) held the shared DB.
- **E-13 (N1) — commit hash.** The caption-removal commit is **`3e2ddb5`**, not `3e2dd5b`. If a citation fails `git show`, the gap-B premise is still independently checkable: `grep -rn "IP-level" apps/web/{src,public,e2e}` must return exactly two source comments plus the `:214` assertion.

28. Create `tests/unit/test_reveal_display_policy.py` — grid over `choose_display_mode` covering **the 8 rows that are testable at this boundary** (**PVL gap E — "exhaustive 9-row" struck**: row 7 `country_disagreement` collapses to `geo is None` inside `build_geo` (step 13) *before* `choose_display_mode` runs, so at this function's boundary it is indistinguishable from row 8; row 7 is proven instead by the both-routes `reason` pair in step 31), plus `apply_display_mode` stripping assertions (assert `"lat" not in geo` for `country`, `city == ""`, `geo is None` for `none`).
29. Create `tests/unit/test_mobile_carrier.py` — ASN hits for all 7 carriers, regex fallback hits over the explicit brand-token list, the `"Mobilezone Datacenter GmbH"` boundary case, **the `"FPT Telecom"` fixed-line → NOT mobile fixture (PVL gap I)**, malformed geo → `False`, and the no-`company_resolver`-import source assertion.
30. Extend `tests/unit/test_geoip_crosscheck.py` — country parse from ipinfo payload, missing-country cache line → `None`, positive disagreement → `False`, mock branch values. **(PVL gap A — softened.)** There is exactly **ONE** equality assertion in this file (`test_geoip_crosscheck.py:110`, `assert result == CrossCheck()`); the other occurrences are keyword constructions. Adding `second_country: str = ""` and `country_agreed: bool | None = None` **with defaults is non-breaking — verified, and the file is 33-passed green right now**. Do **not** pre-emptively churn passing assertions; touch them only if a run proves otherwise.
30a. **(PVL gap R1/H1 — RUN THE INTEGRATION BASELINE FIRST. Mirrors step 31a; do this before extending the integration file.)** Run `.venv/bin/python -m pytest tests/integration/test_onboarding_canary_api.py -q` **once, before writing any new case**, and record the verbatim result in the phase report. Do **not** compare the full lane against any written-down number — re-measure it in-session. If the run shows `asyncpg UniqueViolationError ... pg_type_typname_nsp_index` / `CREATE TYPE ... AS ENUM` errors, that is a **concurrent session** holding the shared dev Postgres `:5433` (confirm with `ps aux | grep [p]ytest`), **not** a red baseline and **not** a source defect: wait for the other run to finish and re-run. Never punt a gate on contention (E-11, E-12).
31. Extend `tests/integration/test_onboarding_canary_api.py` — one case per display mode on both `/onboarding/canary` and `/demo/canary`; anti-regression assertion that no response contains `ip`/`site_id`/`visitor_id`/`fingerprint`; assert `lat` is absent in `country` mode; assert `shown["display_mode"]` is server-stamped even when the client posts a lie. **(PVL C4)** Add a case on BOTH routes asserting `display_mode == "none"` AND `reason == "country_disagreement"` when the second provider positively disagrees on country, and a companion case asserting `reason == "provider_unavailable"` when `geo_raw is None` — this pair is the only place row 7 is distinguishable from row 8.
31a. **(PVL gap B — RUN THE BASELINE FIRST. Do this before writing any new e2e leg.)** Run `cd apps/web && npx playwright test e2e/onboarding-canary.spec.ts` and **record the verbatim result in the phase report**. The spec is **known-red today**: `:214` asserts `await expect(reveal).toContainText("IP-level estimate")`, but that caption was **deleted from the product** at commit `3e2ddb5`; `grep -rn "IP-level" apps/web/{src,public,e2e}` finds only two source COMMENTS plus that assertion, so no renderable source emits the string and the leg cannot pass. Without this baseline step, the plan's own red-gate escape hatch would let AC-7's only automated proof be punted to a follow-up while Section G is called done — the exact vacuous-green outcome the `icp_fit` precedent warns against.
31b. **(PVL gap B — repair by DELETION.)** Delete the stale assertion at `apps/web/e2e/onboarding-canary.spec.ts:214`. **Never restore any `IP`-bearing caption to make it pass** — D6 forbids the token in user-facing copy, and the honesty affordance it used to provide now rests on the accuracy circle (`canary-reveal.tsx:25-32`, rendered by `canary-map.tsx:167-168`). Re-run the spec and confirm the baseline is green **before** adding any new leg. A new leg written on a red baseline proves nothing.
31c. **(PVL F4 re-tier, corrected to Hybrid by PVL gap B.)** Extend `apps/web/e2e/onboarding-canary.spec.ts` with a **public-funnel leg**: `page.goto('/onboarding')` (served from `/beam/onboarding.html` per `next.config.mjs:58`; the route is public per `middleware.ts` `isPublicRoute`), `page.route('**/api/v1/demo/canary', ...)` returning a canned `country` payload, then assert the country card is visible (`data-testid="canary-country-card"`), that no Leaflet container is ever created, and **(PVL gap G)** that the legacy `◎` place row is absent. Add a `map`-payload leg asserting the inverse (map present, country card absent). Also re-check the spec's existing assertions against the widened `RevealMode` and the removed low-confidence rendering.

    **Real gate tier: Hybrid, not Fully-Automated.** `playwright.config.ts` runs this spec under the `chromium` project with `storageState: e2e/.auth/user.json` and `dependencies: ["setup"]`, so the gate requires **uvicorn on :8000 + PG 5433 + Redis 6379 + a successful `auth.setup.ts` user provision**. The route being public removes the *per-test* auth requirement, not the project-level setup dependency.
31d. **(PVL gap H — deploy-skew safety net; currently ZERO coverage.)** Add a **third** funnel leg posting a **`display_mode`-LESS** canned payload (an old server + new JS) and assert the funnel falls back to today's legacy geo-presence rendering path verbatim — map when coords are usable, text otherwise, no crash, no country card. This is the only gate covering new-JS-against-old-API, and the funnel's fallback branch (step 25a) is otherwise untested.
32. Extend `apps/web/src/lib/canary-reveal-mode.test.ts` — the 4-mode matrix, `display_mode` absent → legacy behaviour, `"map"` + `tileState:"failed"` → `"text"`, `"country"` + `"failed"` → still `"country"`.
32a. **(PVL gap D — AC-12 de-vacuation. Three user-facing whole-token `IP` strings survive OUTSIDE the single scanned file; without these three rewordings AC-12 is vacuously green.)** Reword all three jargon-free in the same product voice, keeping the funnel and React copy **identical** where they mirror each other:

    | # | File | Line | Current (banned) | Reword to |
    |---|---|---|---|---|
    | 1 | `apps/web/public/beam/onboarding-steps.js` | `:446` | ``but here's what your IP alone says:`` | ``but here's what your connection alone says:`` |
    | 2 | `apps/web/src/lib/onboarding-script.ts` | `:87` (`REVEAL_GEO_ONLY`) | ``but here's what your IP alone says:`` | ``but here's what your connection alone says:`` (must stay byte-identical to #1) |
    | 3 | `apps/web/src/components/onboarding/onboarding-flow.tsx` | `:269` | ``noted — 'wrong city' goes straight to the team that tunes IP geo.`` | ``noted — 'wrong city' goes straight to the team that tunes location guessing.`` |

    Wording may be refined — the D6 register (lowercase, playful-honest, zero tech jargon) may not. The non-user-facing JSDoc at `onboarding-script.ts:78` and the source comments at `onboarding-steps.js:197` / `canary-format.ts:16` are **not** user-facing strings and are explicitly out of scope.
33. Extend `apps/web/src/lib/canary-format.test.ts` — the D6 banned-substring scan over every exported copy string, using the **normative scan semantics** in §Design → Copy (case-SENSITIVE whole-token for `IP`/`ASN`; case-INSENSITIVE substring for `geolocation`/`database`/`crosscheck`), plus one note-selection case per country-card sub-case. **Delete the `formatConfidenceNote` `describe` block** (`canary-format.test.ts:138-176`) as part of the F3 deletion — the function no longer exists.

**Section I — close-out**

34. Run the full gate matrix (Verification Evidence). Fix in place; do not batch to the end — run each section's gates as that section completes.
35. Confirm `location_reveal_enabled` remains `False` in `apps/api/config.py` and that **this plan added no migration**. **(PVL gap I — scope the check to this plan's own delta.)** Do **not** assert a globally clean `apps/api/migrations/`: this is a shared worktree and sibling sessions legitimately dirty that directory. Assert instead that no migration file appears in **this plan's** changed-file set — e.g. compare against the pre-EXECUTE `git status` snapshot, or check that no file under `apps/api/migrations/` is among the files this execution touched. A pre-existing dirty migrations dir is not this plan's failure.

---

## Phase Completion Rules

This plan is a single COMPLEX phase executed as Sections A-I. Status vocabulary:

- **CODE DONE** — all checklist items applied, no gates run yet. Never report this as done.
- **🧪 TESTING** — Fully-Automated + Hybrid gates green; the two Agent-Probe rows still open.
- **✅ VERIFIED** — every Fully-Automated and Hybrid gate green AND the backlog stub written for the
  Agent-Probe residuals AND the mock-mode map check (AC-13) passed AND the user has explicitly confirmed the reveal renders correctly on real networks. Flag-OFF-only evidence never
  qualifies for VERIFIED on the flag-ON display paths.
- **BLOCKED** — record the specific non-environmental blocker. "Docker unavailable" is not valid in
  this repo (`process/context/tests/all-tests.md`).

Section gates run as each section completes — do not batch them to the end. A section whose gates
are red blocks the next section unless the failure is out of blast radius, in which case it becomes
a follow-up artifact and execution continues.


## Verification Evidence

Detect the container first: `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`. "Docker unavailable" is not an acceptable blocker in this repo.

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/python -m pytest tests/unit/test_reveal_display_policy.py -q` — 8-row grid green (rows 1-6, 8, 9 — row 7 is proven by the both-routes `reason` pair in step 31, not here) | Fully-Automated | AC-1, AC-2, AC-3, AC-8 |
| `.venv/bin/python -m pytest tests/unit/test_mobile_carrier.py -q` — carriers + purity assertion green | Fully-Automated | AC-5, AC-9 |
| `.venv/bin/python -m pytest tests/unit/test_geoip_crosscheck.py -q` — 33 existing + new country cases green | Fully-Automated | AC-4, AC-10 |
| `.venv/bin/python -m pytest tests/unit -m unit -q` — whole unit lane, no regression | Fully-Automated | AC-11 |
| `.venv/bin/python -m pytest tests/integration/test_onboarding_canary_api.py -q` — per-mode payload shape, both surfaces | Hybrid (needs PG 5433 + Redis 6379) | AC-1..AC-3, AC-6, AC-7 |
| `.venv/bin/python -m pytest tests/ -m integration -q` — full integration lane unchanged — **re-measure the baseline in-session immediately before EXECUTE; do not trust a written-down number** (the lane grows with sibling programs; 661 collected as of PVL cycle 3). Baseline-first step: 30a | Hybrid (same precondition) | AC-11 |
| `cd apps/web && npm run test` — `canary-reveal-mode.test.ts` + `canary-format.test.ts` incl. banned-substring scan | Fully-Automated | AC-2, AC-6, AC-12 |
| `cd apps/web && npm run lint` clean | Fully-Automated | AC-11 |
| `MOCK_EXTERNAL_APIS=true` reveal renders the **map** locally (row 1) | Hybrid (local dev server) | AC-13 |
| `cd apps/web && npx playwright test e2e/onboarding-canary.spec.ts` — baseline green after the `:214` repair (steps 31a/31b), then: country payload → country card, no Leaflet, no legacy place row; map payload → inverse; `display_mode`-less payload → legacy fallback | **Hybrid** (**re-tiered again by PVL gap B** — the route is public, but `playwright.config.ts` gives the `chromium` project `storageState` + `dependencies: ["setup"]`, so the gate needs **uvicorn :8000 + PG 5433 + Redis 6379 + a successful `auth.setup.ts`**). **Baseline is RED until step 31b repairs `:214`.** | AC-7 |
| Real VPN / real mobile hotspot produce the country card with the right copy | Agent-Probe (needs real networks; manual, pre-flag-flip) | AC-3, AC-5 |

**Known-gap → backlog stub (required, keeps the gate CONDITIONAL):** exactly ONE genuine Agent-Probe residual remains (the public-funnel leg is re-tiered **Hybrid** per PVL gap B). Write `process/features/onboarding-canary/backlog/reveal-policy-real-network-matrix_NOTE_17-08-26.md` recording the real VPN + real mobile-hotspot manual reveal matrix required before any prod flag flip. Neither gate may be marked PASS on flag-OFF evidence alone — the marketing-claims-gap `icp_fit` silent no-op is the precedent: a flag-gated feature is unproven until the flag-ON path executes against real infra.

---

## Acceptance Criteria

Derived from D1-D6 plus the instrumentation and mock-mode invariants.

| ID | Criterion | proven by / strategy |
|---|---|---|
| AC-1 | `display_mode == "map"` **only** when confidence `high` AND kind ∉ {relay, datacenter, cdn} AND not mobile (D1) | `test_reveal_display_policy.py` rows 1, 9 / Fully-Automated |
| AC-2 | Every D2 trigger (low, unverified, mobile-with-high, vpn/relay) yields `"country"` | `test_reveal_display_policy.py` rows 2-6 + `canary-reveal-mode.test.ts` / Fully-Automated |
| AC-3 | VPN/relay country card carries the vpn disclaimer copy, not the uncertain copy | `canary-format.test.ts` note-selection case / Fully-Automated |
| AC-4 | A positive second-provider **country** disagreement yields `display_mode: "none"` + `reason: "country_disagreement"`; unknown country does **not** (accepted residual) | **(re-pointed by PVL C4)** `test_geoip_crosscheck.py` (the `country_agreed` computation) / Fully-Automated **+** `test_onboarding_canary_api.py` step 31 asserting `reason == "country_disagreement"` on both routes / Hybrid. Row 7 of `test_reveal_display_policy.py` does **not** prove this — step 13 collapses row 7 to `geo is None` before `choose_display_mode` runs, making it indistinguishable from row 8 at that boundary. |
| AC-5 | Mobile-carrier connections are detected for all 7 seed carriers and never reach `"map"` | `test_mobile_carrier.py` / Fully-Automated |
| AC-6 | In `country` mode the response carries **no** `lat`/`lng`/`accuracy_km` and `city == ""` — the client cannot leak a name it was never sent (D8) | `test_onboarding_canary_api.py` / Hybrid |
| AC-7 | Both surfaces behave identically; the public vanilla funnel honours `display_mode`, including the legacy `display_mode`-less fallback (D7) | integration both-routes case (Hybrid) + the three Playwright funnel legs of steps 31c/31d (**Hybrid** — needs uvicorn :8000 + PG + Redis + `auth.setup.ts`; baseline repaired by steps 31a/31b) |
| AC-8 | Geo `None` / Null Island / provider failure yields `"none"` and the no-claim line — never a fabricated pin (D3) | `test_reveal_display_policy.py` row 8 / Fully-Automated |
| AC-9 | `mobile_carrier.py` imports nothing from `company_resolver`; `classify_org_kind` source is unchanged (D5) | `test_mobile_carrier.py` source assertion (durable) + `git diff --exit-code apps/api/services/company_resolver.py` / Fully-Automated. **(PVL gap I — gate limitation.)** The `git diff` half is **committable-around**: it only proves anything while the tree is uncommitted, and reads clean the moment a change to that file is committed. The durable half of AC-9 is the in-test source assertion; run the diff gate **before** any commit in Section I. |
| AC-10 | Pre-existing `geoipx:` cache lines without `country` do not crash and degrade to unknown | `test_geoip_crosscheck.py` / Fully-Automated |
| AC-11 | No regression: unit lane, integration lane, and web lint all green at their prior baselines | full-lane gates / Fully-Automated + Hybrid |
| AC-12 | No user-facing copy string contains `IP`, `geolocation`, `database`, `ASN`, or `crosscheck` (D6) — **across every file that carries reveal copy**, not just the one that is scanned | **(re-scoped by PVL gap D)** `canary-format.test.ts` banned-substring scan over `canary-format.ts` exports / Fully-Automated **+** step 32a rewording of the three strings the scan structurally cannot see: `onboarding-steps.js:446`, `onboarding-script.ts:87`, `onboarding-flow.tsx:269`. **Recorded exceptions (out of scope, non-user-facing):** JSDoc/source comments at `onboarding-script.ts:78`, `onboarding-steps.js:197`, `canary-format.ts:16`. The funnel's mirrored copy strings remain unscanned by any automated gate — that residual is Risk #5. |
| AC-13 | `MOCK_EXTERNAL_APIS=true` still lands on the **map** path | mock-mode probe / Hybrid |
| AC-14 | `ip_family` logging and `shown["ip_family"]` stamping are preserved on every path; `shown["display_mode"]` is added server-side with no migration | integration assertion + `git status` showing no migration / Hybrid |

---

## Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | The public vanilla funnel is left unupdated → policy unenforced where most reveals happen | Section G is a mandatory checklist section; AC-7 gate; the funnel is named in Blast Radius as highest-risk |
| 2 | `to_dict()` growth breaks a `CrossCheck` equality assertion | **(PVL gap A — downgraded.)** Verified: exactly ONE equality assertion exists (`test_geoip_crosscheck.py:110`); defaulted new fields are non-breaking and the file is green at 33 passed. Step 30 says touch existing assertions only if a run proves otherwise. |
| 3 | Mock fixture falls out of the map path → every local demo and every screenshot shows a country card | Section E is a gate, not a hope; AC-13 |
| 4 | Mobile regex false-positives downgrade correct maps | Documented bias (prefer downgrade); boundary fixture in step 29 |
| 5 | Copy drifts between `canary-format.ts` and `onboarding-steps.js` | Cross-reference comments in both files (step 26); step 32a keeps the two mirrored strings byte-identical. **(PVL gap I — pointer corrected.)** No automated gate scans the funnel's copy strings; this residual is **recorded here, in this risk row, and nowhere else**. It is explicitly **NOT** in the `reveal-policy-real-network-matrix_NOTE_17-08-26.md` backlog stub — that stub holds only the real-network matrix residual. Mitigation is the cross-reference comments plus manual review at Section G exit. |
| 6 | Flag-OFF-only evidence declares this done | Explicit note in Verification Evidence; the two Agent-Probe rows keep the gate CONDITIONAL until a flag-ON run |
| 7 | Widening `RevealMode` misses a non-exhaustive `if` chain | Step 22 + grep every `RevealMode` consumer before closing Section F. **(PVL gap I)** Known consumers to sweep explicitly: `canary-reveal.tsx`, `onboarding-flow.tsx`, **`canary-listen.tsx:89`** (`chooseRevealMode(data) !== "skip"`), and the funnel's own duplicate at `onboarding-steps.js:187-195` + `:459`. |

---

## Test Infra Improvement Notes

- **`apps/web/e2e/onboarding-canary.spec.ts` becomes a reusable public-route harness — AFTER repair, not as-is.** **(corrected by PVL gap B.)** It mocks the canary API at the network layer, and `/onboarding` → `/beam/onboarding.html` is genuinely public (`next.config.mjs:58`, `middleware.ts` `isPublicRoute`), so per-test auth is not needed. But the spec is **red today** (`:214` asserts a caption deleted at `3e2ddb5`) and the `chromium` project still carries `storageState` + `dependencies: ["setup"]`, so the gate is **Hybrid** (uvicorn :8000 + PG + Redis + `auth.setup.ts`), not Fully-Automated. Two durable lessons: check route publicity before tiering a browser gate Agent-Probe, **and** run any pre-existing spec once to establish its baseline before tiering a new leg on top of it.
- **`npm run test` (vitest, `environment: node`) cannot render components.** `canary-country-card.tsx` mounting and `canary-reveal.tsx` branching are unprovable in the current frontend unit lane; they are only reachable via Playwright. A jsdom/RTL lane would close this, and is the single largest frontend coverage gap this plan runs into.
- **No automated gate exercises `location_reveal_enabled=True`.** Every gate here runs flag-OFF or mocked. Per the `icp_fit` precedent, that evidence is vacuous for a flag-gated display feature. A flag-ON integration fixture would be a durable infra win well beyond this plan.

---

## Resume and Execution Handoff

1. **Selected plan file:** `process/features/onboarding-canary/active/reveal-display-policy_17-08-26/reveal-display-policy_PLAN_17-08-26.md`
2. **Last completed step:** PLAN written. No code touched.
3. **Validate-contract status:** written — `Gate: CONDITIONAL` at cycle 3 (terminal classification: the flag-ON path is structurally ungated pre-flip; supplement cycle 3 transcription applied). Prior state for the record: `Gate: BLOCKED` at cycle 2; **PVL supplement cycle 2 applied 17-08-26** (merged gap groups A–I from validate G1–G6 + the external adversarial verifier's 15 findings). Cycle 1's P1–P8 are superseded: gap A re-applied the three that were declared-but-not-applied (step 19 `_mock_geo` licence, step 24 circle target, step 30/Risk#2 assertion-churn). Cycle 3 re-validated from V1 and returned CONDITIONAL with 0 FAILs / 2 CONCERNs (H1, H2); supplement cycle 3 has now applied R1-R6 (H1, H2, N1-N3, N5 + E-11/E-12/E-13 transcription).
4. **Supporting context loaded:** `process/context/all-context.md`, `process/context/tests/all-tests.md`, `process/features/onboarding-canary/active/canary-onboarding_10-08-26/canary-onboarding_PLAN_10-08-26.md` (parent feature plan), and the source files named in Touchpoints.
5. **Next step for a fresh agent:** re-run VALIDATE from V1 against this supplemented plan. Do not start EXECUTE without a validate-contract. On entering EXECUTE, work Sections A → I in order and run each section's gates as that section completes; detect the container with the `lsof` command, never `which docker`.

---

## Validate Contract

Status: CONDITIONAL
Date: 17-08-26
date: 2026-08-17
generated-by: outer-pvl
supersedes: 2026-08-17 (outer-pvl) — PVL cycle 3 re-validation after supplement cycle 2

PVL cycle: 3 (supplement cycle 2 applied; re-validated from V1)

Parallel strategy: sequential (any remaining supplement edits one file; EXECUTE is also recommended sequential — see below)
Rationale: signal score 3/7 (S2 public-API contract change, S6 high-risk class, S7 14 files). MEDIUM band nominally suggests parallel subagents, but Sections F and G must keep their D6 copy strings **byte-identical** across two files that cannot import from each other — a mid-run coordination requirement that fire-and-forget subagents structurally cannot honour. Sequential (1 agent, opus) is the fit. Alternative if parallelism is wanted: agent-team, 2 members (backend A–E / frontend F–G) × 2 rounds = 4 agents, with SendMessage used to sync the copy strings; NOT parallel subagents.

Fan-out disclosure: this pass ran **single-pass sequential**, not the designed Layer-1/Layer-2 parallel fan-out. The validate-agent had no Agent tool in this environment. Every dimension below was checked by direct file reading and by read-only commands; no fan-out is claimed.

### Cycle-2 gap closure audit (all 9 merged groups A–I re-checked against source, not against the supplement's own grep-proof)

| Group | Verdict | Independent evidence |
|---|---|---|
| A — declared-applied-but-not (step 19 / step 24 / assertion churn / anchors) | **CLOSED** | Step 19 now reads "**Do NOT modify `_mock_geo`**" (plan :328) with the E1 table inlined at :318-327; step 24 carries the explicit do-not-touch for `canary-map.tsx` (:345); the one-assertion correction is in all three places (:129 Contract §2, :360 step 30, :454 Risk #2). Anchors re-resolved against source: `onboarding.py:106` `crosscheck_geo` / `:108` `build_geo` / `:109` `build_network` ✅; `demo.py:408` `provider_unavailable` ✅; funnel `wantsMap` computed at `:459`, interpolated at `:461` ✅; `hasUsableGeo` `:179-185` ✅ (the cycle-2 contract's own `:186-192` / `:194-202` were the wrong ones — the supplement's numbers are right). |
| B — e2e baseline red + tier overclaim | **CLOSED** | Steps 30a/30b added. Verified independently: `e2e/onboarding-canary.spec.ts:214` is exactly `await expect(reveal).toContainText("IP-level estimate");`, and `grep -rn "IP-level" apps/web/{src,public,e2e}` returns exactly two source COMMENTS (`canary-reveal.tsx:26`, `onboarding-steps.js:197`) plus that assertion — no renderable source emits the string, so the leg is deterministically unpassable. Tier corrected to **Hybrid** in all three places (:366, :419, :438); `playwright.config.ts` confirms `chromium` carries `storageState: e2e/.auth/user.json` + `dependencies: ["setup"]` + a uvicorn `:8000` webServer. Test Infra note softened (:465). |
| C — F3 deletion premise + exact sites | **CLOSED** | The corrected premise is **factually true**: `canary-reveal.tsx:107-111` sits outside the `mode === "map"` branch (:54-60) and beside the `mode === "text"` branch (:113) — it is not mode-gated, and `country` mode still ships `confidence`, so the function would fire under the new card. Deletion table verified line-by-line: `canary-format.ts:163-170` = the function ✅; `canary-reveal.tsx:6` import ✅, `:47` call ✅, `:107-111` JSX + testid ✅; funnel `:144-154` = mirrored comment (`:144-147`) + function (`:148-154`) ✅; `:450` call ✅; `:467` interpolation ✅. **The DO-NOT-TOUCH fence is correct and load-bearing**: `onboarding-steps.js:155-160` is the head of `formatNetwork` including `if (!net) return null;` / `if (!label) return null;` and the `relay`/`cdn` copy `switch`. E-8's zero-hit grep is the right exit condition. |
| D — AC-12 vacuity | **CLOSED — and independently proven complete.** | An independent enumeration (`grep -rnE "\bIP\b\|\bASN\b"` + case-insensitive `geolocation\|database\|crosscheck` across `canary-format.ts`, `onboarding-script.ts`, `components/onboarding/*.tsx`, `onboarding-steps.js`, comments filtered) returns exactly **7** user-facing hits: `canary-format.ts:167,169` and `onboarding-steps.js:152,153` (all four inside the two `formatConfidenceNote` bodies → removed by group C) plus `onboarding-script.ts:87`, `onboarding-flow.tsx:269`, `onboarding-steps.js:446` (→ reworded by step 32a). **Zero survivors.** The three replacement strings are themselves clean. The plan's claim at :229 ("no retained string in `canary-format.ts` trips this scan") holds — the only residue is the JSDoc at `:16`, a recorded exception. |
| E — 8 testable rows / precedence-2 sited / mobile-copy reconciliation | **CLOSED** | Step 28 strikes "exhaustive 9-row" (:358); precedence rule 2 is marked implemented-in-`build_geo`-not-in-the-decider (:165). The mobile-copy reconciliation at :222 is **logically exhaustive**: cross-checking the decision table, the only rows reaching `country` with `confidence == "high"` are row 2 (mobile) and row 3 (relay/datacenter/cdn), and row 3 is separable client-side by `network.kind` — so step 21a's ordering (kind → high → else) is correct and complete, including the rung-5 `network === null` case (falls through to the confidence test, which is the right answer). |
| F — React no-claim parity | **CLOSED** | Step 22a (:339) renders the same D6 no-claim line on the React `none`-with-journey path. Closes a real D7 divergence. |
| G — country-mode double country claim | **CLOSED — the defect is real.** | Verified by reading `formatPlace` (`canary-format.ts:76-90`): with `city=""`, `region=""`, `country_code="US"` it returns the bare `cc`, i.e. `"US"`. Both suppressions are specified (React :343 targeting `canary-reveal.tsx:46`/`:66`; funnel :351 targeting `:463` fed by `:449`) and asserted in step 31c. |
| H — funnel legacy-fallback leg | **CLOSED** | Step 31d adds the third `display_mode`-less Playwright leg — the only new-JS-against-old-API coverage. |
| I — six NOTE fixes | **CLOSED** | `canary-listen.tsx:89` verified as `chooseRevealMode(data) !== "skip"` and now in Touchpoints (:87) + Risk #7 (:459); step 35's migration gate scoped to this plan's own delta (:383) — correct, the worktree is genuinely dirty from sibling sessions; Risk #5 stub pointer fixed (:457); the row-9 label-less-relay gap is recorded (:171) and is **factually correct** — `build_network` returns `None` at `onboarding_canary.py:233`, before `is_privacy_relay_ip` is consulted at `:239`; AC-9's committable-around limitation recorded (:440); the mobile brand-token list is explicit and the `"FPT Telecom"` fixed-line fixture is specified (:207-208, :359). |

### Independent re-derivations requested at cycle 3

**(1) Blast-radius count — RE-DERIVED FROM THE TOUCHPOINTS LIST, CONFIRMED CORRECT.** Counting the Touchpoints entries myself: backend changed = `geoip_crosscheck.py`, `onboarding_canary.py`, `routers/onboarding.py`, `routers/demo.py` (**4**); backend new = `mobile_carrier.py` (**1**); frontend changed = `canary-format.ts`, `canary-reveal-mode.ts`, `canary-reveal.tsx`, `canary-listen.tsx`, `canary-map.tsx`, `onboarding-flow.tsx`, `onboarding-script.ts`, `onboarding-steps.js` (**8**); frontend new = `canary-country-card.tsx` (**1**). Total **14** ✅ matches the claim exactly. Test files: `test_geoip_crosscheck.py`, `canary-reveal-mode.test.ts`, `canary-format.test.ts`, `test_onboarding_canary_api.py`, `onboarding-canary.spec.ts` (5 changed) + `test_mobile_carrier.py`, `test_reveal_display_policy.py` (2 new) = **7** ✅, and the sub-breakdown (2 new backend unit / 2 changed frontend unit / 1 changed backend unit / 1 changed integration / 1 changed e2e) sums correctly. All 21 existing paths resolve on disk; all 4 new paths are correctly absent.

**(2) Structural-validator warning — the "false positive" claim is HALF RIGHT; refuted as stated.** The validator emits 0 failures / 1 warning: *"uses VERIFIED without explicit user-confirmation language"*. Reading the rule (`validate-plan-artifact.mjs:112`), it fires when `✅ VERIFIED` is present and none of `User Confirmation|user confirmed|user-confirmed|confirmed working|user says` matches. The plan's Phase Completion Rules say *"the **user has explicitly confirmed** the reveal renders correctly on real networks"* — semantically this **is** user-confirmation language, so the warning is not a substantive defect. But it is **not** a validator bug either: the phrasing genuinely does not match any accepted form, so the warning will recur on every future run and will keep costing a cycle to re-adjudicate. Verdict: **semantic false positive, mechanical true positive.** A one-word reword ("…AND the **user confirmed** the reveal renders correctly on real networks") clears it permanently. Recorded as N7 below; warnings are advisory and do not gate.

### Net gate derivation

| Layer 1 dimension | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | CONCERN |
| Breaking changes | PASS |
| Security surface | PASS |

| Layer 2 section | Status |
|---|---|
| A — country hardening (backend) | PASS |
| B — mobile detection (backend, new) | PASS |
| C — display-mode decision (backend) | PASS |
| D — routers (both surfaces) | PASS |
| E — mock-mode landing check | PASS |
| F — frontend shared lib | PASS |
| G — public vanilla funnel | PASS |
| H — tests | CONCERN |
| I — close-out | PASS |

**Totals: 0 FAILs / 2 CONCERNs / 11 PASSes → Net Gate: CONDITIONAL**

Both cycle-2 FAILs (G1, G2) and all four CONCERNs (G3–G5 + the anchor NOTEs) are **CLOSED, verified against source rather than against the supplement's own grep-proof lines**. The design, the eight locked decisions, the 9-row table, the pure `choose_display_mode` / `apply_display_mode` split and the D5 module placement are untouched for a third consecutive cycle and are NOT re-litigated. The defect class has narrowed again: cycle 1 was missing checklist steps, cycle 2 was wrong deletion ranges, cycle 3 is **stale bookkeeping inside the plan's own gate table**.

Independently, the net gate could not have been a terminal PASS regardless of the findings below: the flag-ON display path has **no** automated gate at any tier (every gate runs `location_reveal_enabled=False` or against mocks), so it is a named residual, and a PASS resting on it would be vacuously green. CONDITIONAL is the correct terminal classification for this plan, not a punishment.

### Gaps (cycle 3)

| # | Gap | Severity | Proposed fix |
|---|---|---|---|
| H1 | **The integration Hybrid gate carries a stale baseline number and no baseline-first step — the exact hazard gap B installed a fix for on the *other* browser gate, left unfixed on the gate that proves more.** Verification Evidence (:415) says *"full integration lane unchanged (**537 baseline**)"*. Measured this cycle: `pytest tests/ -m integration -q --collect-only` reports **661 collected** (3003 deselected). The 537 figure is inherited from `all-context.md`'s 07-08-26 measurement and the tree has since moved (marketing-claims-gap alone landed three phases of tests). Separately and more importantly: running `pytest tests/integration/test_onboarding_canary_api.py -q` three times on this machine produced **20 passed/7 errors → 18/9 → 15/12** — an escalating `asyncpg UniqueViolationError: duplicate key ... pg_type_typname_nsp_index ... CREATE TYPE platform AS ENUM` failure. Root cause identified: a **concurrent session** was running `pytest tests/ -m integration` against the same shared dev Postgres `:5433` (PID 23769, observed live), and two runs collide on conftest's `DROP TYPE`/`create_all` cycle. That is contention, **not** a red baseline and **not** a source defect — but the plan says nothing about it, so an execute-agent that hits it will either mis-attribute the errors to its own change and thrash, or reach for the plan's own escape hatch ("a section whose gates are red blocks the next section unless the failure is out of blast radius, in which case it becomes a follow-up artifact") and punt AC-6 / AC-14 — the vacuous-green outcome the plan's `icp_fit` precedent exists to prevent. | CONCERN | Replace "(537 baseline)" with "baseline re-measured immediately before EXECUTE — do not trust a written-down number; the lane grows with sibling programs". Add a Section H step mirroring 30a for the integration gate: run `pytest tests/integration/test_onboarding_canary_api.py -q` once before extending it and record the verbatim result in the phase report. Add one execute-instruction: `pg_type ... already exists` / `CREATE TYPE ... AS ENUM` errors on `:5433` mean a **concurrent session is running the integration lane** — re-check with `ps aux \| grep [p]ytest`, wait for it to finish and re-run; this is contention, never a regression, and never grounds to punt a gate. |
| H2 | **Two stale sentences inside the plan's own gate tables contradict corrections the same supplement applied elsewhere.** (a) Verification Evidence :410 still describes `test_reveal_display_policy.py` as a "**9-row grid green**", but step 28 (:358) explicitly strikes "exhaustive 9-row" and scopes the file to **8** testable rows (row 7 collapses to `geo is None` inside `build_geo` before the decider runs) — and the Test Gates table below correctly says "rows 1-6, 8, 9". An agent reading the gate row first may try to author a row-7 case at a boundary where it is indistinguishable from row 8, and the only ways out are a fabricated assertion or a wasted cycle. (b) The known-gap paragraph :422 still justifies the single Agent-Probe residual with "*the public-funnel leg is re-tiered **Fully-Automated** per PVL F4*" — but gap B re-tiered that leg to **Hybrid**, as :366, :419 and :438 all now say. The conclusion (one Agent-Probe residual) survives; the stated reason is now false. | CONCERN | (a) Change :410 to "8-row grid green (rows 1-6, 8, 9 — row 7 is proven by the both-routes `reason` pair in step 31, not here)". (b) Change :422 to "…the public-funnel leg is re-tiered **Hybrid** per PVL gap B". |
| N1 | Commit hash typo: steps 30a/30b and the Test Infra note cite commit **`3e2dd5b`** for the caption removal. `git log --oneline -1 3e2dd5b` → `fatal: ambiguous argument`. The real commit is **`3e2ddb5`** ("feat(onboarding): drop IP-estimate caption, make the canary map zoomable"), confirmed via `git log --all -S "IP-level estimate"`. The cycle-2 contract had it right; the supplement transposed two characters. Low impact — the gap-B premise is independently self-verifiable by the `grep -rn "IP-level"` the plan also supplies (and which I ran: 2 comments + 1 assertion, exactly as claimed) — but an agent that runs `git show` on the bad hash and gets `fatal` may distrust the whole instruction. | NOTE | Correct to `3e2ddb5` in all three places. |
| N2 | Section H step order is `28, 29, 30, 31, 30a, 30b, 31a, 31b, 32, 32a, 33` — the two baseline-first steps (30a/30b) are printed **after** step 31. Functionally safe, because 30a states its own ordering constraint in its first line ("do this before writing any new e2e leg") and 31a/31b are the new legs. Cosmetic but it is the one section where ordering carries correctness weight. | NOTE | Renumber to 31a/31b (baseline+repair) → 31c/31d (new legs), or move the two steps above 31. |
| N3 | Carried from cycle-2 N-c, still unapplied (it was flagged "optional" in Q6): the funnel feedback POST at `onboarding-steps.js:532-533` computes `Math.round(geo.lat * 100) / 100` unguarded. In `country` mode `geo` is truthy and `geo.lat` is `undefined` → `NaN` → `JSON.stringify` emits `null`. The emitted value is correct, so this is cosmetic — but it is asymmetric with step 20c, which fixes the byte-identical React expression and justifies itself as "parity". | NOTE | Guard it alongside step 27, or state in step 27 that NaN→null is accepted and deliberately not mirrored. |
| N4 | Carried from cycle-2 N-d, still unapplied (also "optional"): `cdn` is unreachable in a response because `build_network` re-maps `cdn`→`relay` at `onboarding_canary.py:239-240` (verified), so `{relay, datacenter, cdn}` in the decision table and in step 21a has a permanently dead branch. Harmless defensive breadth. | NOTE | One-line comment in the decision table. |
| N5 | Resume and Execution Handoff item 3 (:475) still reads "Gate: BLOCKED at cycle 2 … Awaiting re-validation from V1 (cycle 3)". Now stale — cycle 3 has run. Outside this agent's write scope (contract section only). | NOTE | Refresh at the next supplement. |
| N6 | The locked-decision table below is headed "seven locked user decisions" while the Decision Record defines **D1–D8** (eight). Corrected in this contract's table; the plan body's own phrasing is unaffected. | NOTE | — |
| N7 | Structural validator advisory: `✅ VERIFIED` present without a phrase the validator's regex accepts. Semantically satisfied ("the user has explicitly confirmed…"), mechanically unmatched — will recur every cycle until reworded. See §Independent re-derivations (2). | NOTE | Reword to "…AND the **user confirmed** the reveal renders correctly on real networks". |
| E1' | **Section E remains empirically pre-answered.** No new evidence contradicts the inlined E1 table. Step 19's licence to edit `_mock_geo` is now struck in the plan body, so the protection no longer lives only inside the overwritable contract. | ✅ PASS | Carried as execute-instruction E-1. |
| E2' | **Flag posture PASS — re-confirmed.** `demo.py:361` `_require_location_reveal()` (called `:381`, and again `:467` for the feedback route); `onboarding.py` `_require_flag()`; `location_reveal_enabled` default `False`. Both surfaces dormant. | ✅ PASS | — |
| E3' | **Hybrid preconditions MET — re-verified live this cycle.** `lsof -nP -iTCP -sTCP:LISTEN \| grep -E '5433\|6379'` returns both listeners. Runner baselines measured this cycle: `test_geoip_crosscheck.py` **33 passed in 0.67s**; full unit lane **1963 passed, 2 skipped in 9.47s**; `cd apps/web && npm run test` **12 files, 185 passed in 2.84s**; `apps/web/node_modules/.bin/{vitest,playwright,next}` all present. No Hybrid gate may be deferred as environment-blocked. | ✅ PASS | — |
| E4' | **`CrossCheck` non-breaking claim PROVEN, not merely asserted.** `__eq__` (`geoip_crosscheck.py:82-83`) compares `self.to_dict() == other.to_dict()`, and there is exactly **one** equality assertion in the file (`:110`, `assert result == CrossCheck()`; the only other occurrence at `:221` is a constructor argument). Two defaulted fields therefore cannot break it, and the file is **33 passed** green right now. | ✅ PASS | — |

### Proposed plan updates (apply during supplement cycle 3)

| # | What changes | Where in plan | Why |
|---|---|---|---|
| R1 | Drop the "537 baseline" figure; add an integration baseline-first step mirroring 30a; add the concurrent-session `pg_type` contention execute-instruction | Verification Evidence :415 + § H (new step) + Execute-agent instructions | H1 |
| R2 | Fix the two stale gate-table sentences: ":410 9-row → 8-row (rows 1-6, 8, 9)"; ":422 Fully-Automated → Hybrid" | Verification Evidence :410, :422 | H2 |
| R3 | Correct commit hash `3e2dd5b` → `3e2ddb5` in all three citations | § H steps 30a/30b + Test Infra Improvement Notes | N1 |
| R4 | Renumber or reorder the Section H baseline steps so 30a/30b precede 31 | § H | N2 |
| R5 | Guard the funnel coords at `:532-533`, or state that NaN→null is accepted and deliberately unmirrored; add the `cdn` dead-branch comment | § G step 27 + Design decision table | N3, N4 |
| R6 | Refresh Resume item 3 to cycle 3; reword the VERIFIED line to "the user confirmed …" | Resume and Execution Handoff + Phase Completion Rules | N5, N7 |

### Execute-agent instructions (carry into EXECUTE)

| # | Instruction | Trigger condition |
|---|---|---|
| E-1 | Do **NOT** modify `apps/api/services/geoip.py::_mock_geo`. Section E is pre-answered: the fixture already lands on row 1 (map) via `kind="company"`. If a local run disagrees, re-derive with `classify_org_kind` and report — do not touch any fixture. | Section E entry |
| E-2 | Never use `which docker`. Detect with `lsof -nP -iTCP -sTCP:LISTEN \| grep -E '5433\|6379'`. Both listeners confirmed up at contract time; "environment-blocked" is not an accepted gap category in this repo. | Any Hybrid gate |
| E-3 | Widen the `CanaryGeo` type FIRST, then run `cd apps/web && npm run lint` to enumerate the real call sites rather than grepping by hand. Fix every site the compiler names; do not silence with `!` or `as`. | Section F entry |
| E-4 | Both routers must stay byte-equivalent in policy. After editing `demo.py`, diff the two blocks and confirm the only differences are the `_ip_family` alias and `ANONYMOUS_USER_ID`. | Section D exit |
| E-5 | Preserve `ip=ip[:8]` and `ip_family=` in every structlog line. Never log a city name, a full IP, or a `shown` payload. | Sections A, D |
| E-6 | `shown["display_mode"]` is server-owned. Overwrite whatever the client posted; mirror the existing `test_client_cannot_forge_the_address_family` pattern (`tests/integration/test_onboarding_canary_api.py:695`). | Section D step 16, Section H step 31 |
| E-7 | Run each section's gates as that section completes. Do not batch to the end. | All sections |
| E-8 | After editing `apps/web/public/beam/onboarding-steps.js`, run `grep -n confidenceNote apps/web/public/beam/onboarding-steps.js` and require **zero** hits. A leftover `:467` interpolation is a runtime `ReferenceError` that kills the public reveal card and the file has no compiler to catch it. | Section G exit |
| E-9 | Do **not** delete the accuracy circle from `apps/web/src/components/onboarding/canary-map.tsx:167-168`. It is required in `map` mode and no gate would catch its removal. | Section F entry |
| E-10 | Run the Playwright spec once BEFORE writing new legs and record the baseline. Repair `e2e/onboarding-canary.spec.ts:214` by deleting the `"IP-level estimate"` assertion — never by restoring an `IP`-bearing caption (D6). | Section H entry |
| E-11 | **(new, H1)** Establish the integration baseline the same way: run `.venv/bin/python -m pytest tests/integration/test_onboarding_canary_api.py -q` once before extending it and record the verbatim result. Do **not** compare the full lane against any written-down number — re-measure. | Section H entry |
| E-12 | **(new, H1)** `asyncpg UniqueViolationError ... pg_type_typname_nsp_index` / `CREATE TYPE ... AS ENUM` errors against `:5433` mean **a concurrent session is running the integration lane on the shared dev Postgres** (confirm with `ps aux \| grep [p]ytest`). This is contention, never a regression and never grounds to punt a gate: wait for the other run to finish and re-run. Observed live at contract time — three consecutive runs of the canary file degraded 7 → 9 → 12 errors while a sibling session held the DB. | Any integration gate |
| E-13 | **(new, N1)** The caption-removal commit is `3e2ddb5`, not `3e2dd5b`. If a citation in the plan fails `git show`, the gap-B premise is still independently checkable: `grep -rn "IP-level" apps/web/{src,public,e2e}` must return exactly two source comments plus the `:214` assertion. | Section H entry |

### Backlog artifacts

| Artifact | Location | What it tracks |
|---|---|---|
| `reveal-policy-real-network-matrix_NOTE_17-08-26.md` | `process/features/onboarding-canary/backlog/` | The ONE genuine Agent-Probe residual: real VPN + real mobile-hotspot reveal matrix, required manually before any `location_reveal_enabled` flip. Holds **only** this residual — the funnel copy-drift residual (Risk #5) is deliberately NOT in it. |

### Test gates

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1, AC-2, AC-8 | `choose_display_mode` returns the table's mode for rows 1-6, 8, 9 (8 testable rows — row 7 collapses at the `build_geo` boundary) | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_reveal_display_policy.py -q` | B |
| AC-6 (unit half) | `apply_display_mode` strips `lat`/`lng`/`accuracy_km`, blanks `city`/`region` in `country`, returns `None` in `none` | Fully-Automated | same file | B |
| AC-5, AC-9 | 7 seed carriers detected; `"Mobilezone Datacenter GmbH"` and `"FPT Telecom"` boundary fixtures; malformed geo → `False`; zero `company_resolver` import | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_mobile_carrier.py -q` | B |
| AC-4, AC-10 | Second-provider country parsed; missing-country cache line → `None`; positive disagreement → `False`; mock branch values | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_geoip_crosscheck.py -q` (**33-passed baseline re-verified green this cycle, 0.67s**) | B |
| AC-9 (freeze half) | `classify_org_kind` source unchanged | Fully-Automated | `git diff --exit-code apps/api/services/company_resolver.py` — run **before** any commit (committable-around) | B |
| AC-11 (unit lane) | No unit regression | Fully-Automated | `.venv/bin/python -m pytest tests/unit -m unit -q` (**baseline measured this cycle: 1963 passed / 2 skipped**) | A |
| AC-1..AC-3, AC-6, AC-7, AC-14 | Per-mode payload shape on BOTH routes; `lat` absent in `country`; `reason == "country_disagreement"` vs `"provider_unavailable"`; no `ip`/`site_id`/`visitor_id`/`fingerprint` leak; `shown["display_mode"]` server-stamped against a lying client | Hybrid — precondition: PG 5433 + Redis 6379 (**both re-confirmed listening**) **and no concurrent integration run on the shared DB (E-12)** | `.venv/bin/python -m pytest tests/integration/test_onboarding_canary_api.py -q` — baseline run required first (E-11) | B |
| AC-11 (integration lane) | No integration regression | Hybrid — same precondition | `.venv/bin/python -m pytest tests/ -m integration -q` — **re-measure the baseline; do not trust "537" (661 collected this cycle)** | A |
| AC-2, AC-3, AC-12 | 4-mode `RevealMode` matrix; `display_mode` absent → legacy; D6 banned-substring scan | Fully-Automated | `cd apps/web && npm run test` (**baseline re-verified: 12 files / 185 passed, 2.84s**) | B |
| AC-11 (web) | Lint/type clean after the `CanaryGeo` widening | Fully-Automated | `cd apps/web && npm run lint` | B |
| AC-12 (out-of-scan half) | The three user-facing `IP` strings outside `canary-format.ts` are reworded | Fully-Automated | step 32a + re-run `grep -rnE "\bIP\b" apps/web/src/lib apps/web/src/components/onboarding apps/web/public/beam` and require zero **non-comment** hits (**independently enumerated this cycle: exactly 7 hits today, all 7 covered**) | B |
| AC-7 (funnel, 3 legs) | Public `/onboarding` renders the country card for a `country` payload and never initialises Leaflet; map payload → inverse; `display_mode`-less payload → legacy fallback; legacy `◎` place row absent in `country` mode | **Hybrid** — precondition: uvicorn :8000 + PG 5433 + Redis 6379 + a successful `auth.setup.ts` provision (`chromium` carries `storageState` + `dependencies: ["setup"]`) | `cd apps/web && npx playwright test e2e/onboarding-canary.spec.ts` — **baseline run + `:214` deletion required first (steps 31a/31b)** | B |
| AC-13 | `MOCK_EXTERNAL_APIS=true` still lands on the map path | Hybrid — precondition: local dev server | manual reveal against the local dev server; pre-answered analytically in E1 | A |
| AC-3, AC-5 (real networks) | Real VPN / real mobile hotspot produce the country card with the right copy | Agent-Probe | manual matrix, pre-flag-flip | D |
| flag-ON display path (all ACs) | Any of the above executing with `location_reveal_enabled=True` against real infra | **Known-Gap — named residual, no gate at any tier** | — | D |

gap-resolution legend: A — proven now · B — gate added by this plan's checklist · C — deferred to a named later phase · D — backlog residual.

C-4 reconciliation: the `strategy` column carries only the three proving strategies (Fully-Automated / Hybrid / Agent-Probe). The single Known-Gap row above is a **named residual**, not a strategy that proves anything — it is the reason this gate is CONDITIONAL rather than PASS.

Legacy line form (for existing contract consumers):
- display-mode decision: Fully-automated: `.venv/bin/python -m pytest tests/unit/test_reveal_display_policy.py -q`
- mobile detection: Fully-automated: `.venv/bin/python -m pytest tests/unit/test_mobile_carrier.py -q`
- country hardening: Fully-automated: `.venv/bin/python -m pytest tests/unit/test_geoip_crosscheck.py -q`
- API payload shape (both routes): hybrid: `.venv/bin/python -m pytest tests/integration/test_onboarding_canary_api.py -q` + precondition PG 5433 / Redis 6379 / no concurrent integration run
- frontend policy + copy: Fully-automated: `cd apps/web && npm run test` and `cd apps/web && npm run lint`
- public funnel: hybrid: `cd apps/web && npx playwright test e2e/onboarding-canary.spec.ts` + precondition API :8000 / PG / Redis / auth.setup — baseline + `:214` repair first
- real VPN / mobile matrix: known-gap: documented — backlog stub required
- flag-ON path: known-gap: documented — no gate at any tier; blocks `✅ VERIFIED`, not EXECUTE

Failing stub (`test_reveal_display_policy.py`):
```
test("should return map only when confidence high and kind user-owned and not mobile", () => { throw new Error("NOT IMPLEMENTED — TDD stub: display-mode row 1") })
```
Failing stub (`test_mobile_carrier.py`):
```
test("should detect all seven seed mobile carriers by ASN", () => { throw new Error("NOT IMPLEMENTED — TDD stub: mobile carrier ASN set") })
```
Failing stub (`test_geoip_crosscheck.py`):
```
test("should yield country_agreed False on a positive country disagreement", () => { throw new Error("NOT IMPLEMENTED — TDD stub: country hardening D4") })
```
Failing stub (`canary-format.test.ts`):
```
test("should contain no banned D6 token in any exported copy string", () => { throw new Error("NOT IMPLEMENTED — TDD stub: D6 banned-substring scan") })
```

### Dimension findings

- Infra fit: PASS — every cited anchor re-resolved against source this cycle, not carried forward: `geoip_crosscheck.py:43/60/82/110/123/130/153/213/230`, `onboarding_canary.py:201/233/237/239-240/268/291-340`, `onboarding.py:96/106/108/109/121/130-131/175/317`, `demo.py:361/381/408/415-420/430/441-442`, `canary-format.ts:16/24/27-36/76-90/163-170`, `canary-reveal.tsx:6/25-32/46/47/54-60/66/107-111/113`, `canary-map.tsx:58/92/167-168/192/221`, `onboarding-flow.tsx:248-249/269`, `canary-listen.tsx:89`, `onboarding-script.ts:78/87`, `onboarding-steps.js:144-154/155-160/179-185/187-195/197/396/446/449/450/459/461/463/467/471/527-540`, `e2e/onboarding-canary.spec.ts:214`, `playwright.config.ts:19-33/36-58`, `next.config.mjs:58`, `middleware.ts:18-20`, `tests/unit/test_geoip_crosscheck.py:110`, `tests/integration/test_onboarding_canary_api.py:695`. All 21 existing touchpoint paths present; all 4 new paths correctly absent. Zero anchor drift remains — cycle-2's N-a/N-b are closed and cycle-2's own counter-anchors for `hasUsableGeo`/`chooseRevealMode` were the erroneous ones.
- Test coverage: CONCERN — H1. Every behavior in the blast radius now has a named proving gate at a real tier, the D6 scan is independently proven non-vacuous (7 hits, 7 covered, 0 survivors), the both-routes `reason` pair closes AC-4, and the three-leg funnel matrix closes AC-7 including deploy skew. What remains is bookkeeping on the gate table itself: a stale integration baseline number (537 vs 661 collected), no baseline-first step for the integration Hybrid gate, and no instruction for the shared-DB contention this machine demonstrably produces. Plus the two stale sentences in H2.
- Breaking changes: PASS — `display_mode` is additive and old clients degrade correctly (verified: the funnel reads no `display_mode` today and `reason` already exists on both routes at `onboarding.py:130-131` / `demo.py:441-442`, typed client-side at `canary-format.ts:62`, with zero existing readers of a new `reason` value). `CrossCheck`'s two new fields are provably non-breaking (E4'). `CanaryGeo`'s coord fields become optional with all four dereferencing consumers in Touchpoints and in the checklist (20a/20b/20c, plus `canary-listen.tsx` via the `RevealMode` widening), and the compiler-first strategy (E-3) is the right discovery mechanism. `RevealMode`'s widening has an explicit consumer sweep list (Risk #7).
- Security surface: PASS — no new route, no new auth surface, no new external provider call, no migration. New log fields (`display_mode`, `mobile`, two country codes) are non-PII; `ip=ip[:8]` preserved (E-5). `shown["display_mode"]` is server-stamped over the client value against the existing forge-test pattern. Stripping city/coords server-side in `country` mode is a net privacy improvement and is the whole point of D8. Both surfaces flag-dormant (E2'). The group-C deletion is confirmed **privacy-load-bearing**: leaving `formatConfidenceNote` in place would have printed a city-disagreement hedge underneath the country card, re-leaking exactly what `country` mode exists to suppress.
- Section A (country hardening): PASS — steps 1-6 mechanically complete; the `:130` unpack is named and is the only unpack site; the no-namespace-bump cache-degrade reasoning is sound.
- Section B (mobile detection): PASS — brand-token list explicit; both boundary fixtures specified; the zero-import purity gate is durable (source assertion, not a diff).
- Section C (display-mode decision): PASS — precedence normative and top-down; row 7's collapse sited in `build_geo`; row 9's label-less-relay gap verified factually correct and accepted in writing. N4 note only.
- Section D (routers): PASS — the three-branch `reason` precedence is normative and both routers are held byte-equivalent by E-4.
- Section E (mock mode): PASS — G4 closed; the `_mock_geo` licence is struck in the plan body, not only in the overwritable contract.
- Section F (frontend shared lib): PASS — G2(a)/G2(c)/G3 closed; the accuracy circle is fenced in three places (plan :258, :345, E-9); step 22a closes the React no-claim D7 divergence; step 24's place-row suppression closes the double country claim.
- Section G (public vanilla funnel): PASS — G2(b) closed. `:467` is named three separate times (Design table, the why-not-optional paragraph, step 26a), `:155-160` is fenced with the reason (fabrication guard + relay copy switch), and E-8's zero-hit grep is a mechanical exit condition on a file with no compiler. 25a's decider rewrite lands before 25's markup branch, which is the correct order; `:471`'s `if (wantsMap)` needs no edit because `wantsMap` is derived from the rewritten decider.
- Section H (tests): CONCERN — H1 + H2. No FAIL: the e2e baseline hazard (cycle-2 G1) is genuinely closed, and the fix is correct.
- Section I (close-out): PASS — the migration check is correctly scoped to this plan's own delta rather than to a globally clean `migrations/` dir, which would be unsatisfiable in this shared worktree.

### Locked-decision encoding check (D1–D8)

All **eight** locked user decisions remain correctly encoded; none are re-litigated.

| Decision | Encoded at | Verdict |
|---|---|---|
| D1 map only when high + user-owned + not mobile | rows 1, 9; precedence 3-6 | ✅ |
| D2 country card for low / unverified / mobile / VPN-relay | rows 2-6; copy table; note-selection order in 21a proven exhaustive | ✅ |
| D3 no-claim on fail / Null Island | rows 7, 8; copy table; React parity added by step 22a | ✅ |
| D4 second-provider country compare, disagree → no-claim | § A steps 1-6; residual `country_agreed: None` = allowed; proven by the both-routes `reason` pair | ✅ |
| D5 mobile detection built this pass, `classify_org_kind` frozen | § B; regression fence; AC-9 durable source assertion | ✅ |
| D6 lowercase, zero tech jargon | copy table + normative scan semantics + step 32a; **independently verified complete — 7 user-facing banned-token strings exist today, all 7 are deleted or reworded, 0 survivors** | ✅ |
| D7 all three clients get identical server-decided policy | §§ D, F, G; funnel decider 25a, place-row parity 24/25b, React no-claim parity 22a, deploy-skew leg 31b | ✅ — the crash-capable deletion (cycle-2 G2b) and the red proving gate (cycle-2 G1) are both closed |
| D8 server decides and strips before sending | `apply_display_mode`; payload table; the group-C deletion is what makes it true on the client | ✅ |

### Open gaps

- H1 — integration Hybrid gate: stale "537" baseline (actual 661 collected), no baseline-first step, undocumented shared-DB contention hazard (CONCERN — fix in plan; acceptable-with-record if the orchestrator prefers, since the gate command itself is correct and E-11/E-12 above capture the behaviour)
- H2 — two stale gate-table sentences contradicting corrections applied elsewhere in the same supplement: ":410 9-row" vs step 28's 8 rows, and ":422 Fully-Automated" vs the Hybrid re-tier (CONCERN — fix in plan; acceptable-with-record, since the normative statements elsewhere are correct and the gate commands are unaffected)
- N1…N7 — commit-hash typo, Section H step ordering, funnel NaN guard, `cdn` dead branch, stale Resume line, "seven vs eight" decisions, validator VERIFIED phrasing (NOTE, fix opportunistically)
- Real VPN / real mobile-hotspot matrix — known-gap: documented as backlog stub `reveal-policy-real-network-matrix_NOTE_17-08-26.md`, required before any flag flip. **Excluded from the gate count.**
- Flag-ON display path — known-gap: no automated gate at any tier. **Excluded from the gate count**, but it is the reason a terminal PASS is unavailable for this plan and the reason `✅ VERIFIED` requires explicit user confirmation on real networks.
- Funnel copy-drift (Risk #5) — no automated gate scans `onboarding-steps.js` copy strings; mitigated by cross-reference comments plus manual review at Section G exit. Recorded in Risk #5 only, deliberately not in the backlog stub.

### What this coverage does NOT prove

- `pytest tests/unit/test_reveal_display_policy.py` proves the pure decision function only. It does **not** prove either router calls it, nor that anything is stripped on the wire, nor that a country disagreement is distinguishable from a provider failure (row 7 collapses to `geo is None` before the decider runs).
- `pytest tests/unit/test_mobile_carrier.py` proves the 7 seeded carriers plus the regex and the two boundary fixtures. It does **not** prove coverage of the global mobile-ASN space — any carrier outside the seed set still reaches `map` — nor the false-positive rate of `mobile|cellular|wireless|gsm|lte|4g|5g` against real ISP names in the wild.
- `pytest tests/unit/test_geoip_crosscheck.py` proves the parse, cache-degrade and comparison logic against fixtures. It does **not** prove ipinfo actually returns `country` in the live response shape, nor that a live keyless 429 behaves as fixtured.
- `pytest tests/integration/test_onboarding_canary_api.py` runs against real PG/Redis but with `MOCK_EXTERNAL_APIS=true`, so it proves payload shape and stripping. It does **not** prove any real provider disagreement, any real relay/datacenter classification, or that a real mobile IP is detected. It also does not prove anything at all while a sibling session holds the shared DB (E-12).
- `pytest tests/ -m integration` proves no cross-lane regression **relative to a baseline measured in the same session**. It proves nothing when compared against a written-down number — this cycle demonstrated the written number was 124 tests stale.
- `npm run test` (vitest, `environment: node`) proves pure `src/lib` functions. It does **not** render any component: it cannot prove `canary-country-card.tsx` mounts, that `canary-reveal.tsx` branches correctly, that the place row is actually suppressed, that the accuracy circle survives, or that Leaflet is not initialised.
- `npm run lint` proves type/lint cleanliness. It does **not** prove runtime behaviour with an absent `lat`, and it proves **nothing at all** about `apps/web/public/beam/onboarding-steps.js` — that file is untyped vanilla JS outside the TS program, which is why E-8's grep, not the compiler, is the guard there.
- The three Playwright funnel legs prove the funnel honours a **mocked** `display_mode` (and a mocked absence of it). They do **not** prove the live server emits the right mode for a real caller, and they do not exercise `location_reveal_enabled=true` against real infra.
- The D6 banned-substring scan proves `canary-format.ts` exports are clean. It structurally **cannot** see the funnel's mirrored copy strings — that residual is Risk #5 and is mitigated only by cross-reference comments and manual review.
- **Nothing here proves the flag-ON path.** Every automated gate runs with `location_reveal_enabled=False` or against mocks. Per the `icp_fit` precedent, flag-OFF-only evidence is vacuous for a flag-gated display feature — `✅ VERIFIED` requires the real-network matrix and explicit user confirmation.

Gate: CONDITIONAL (0 FAILs; 2 CONCERNs — H1, H2 — both plan-text bookkeeping on gates whose commands are correct; plus two named known-gap residuals excluded from the count)
Accepted by: NOT ACCEPTED — no self-acceptance is recorded. The two CONCERNs above are offered for acceptance with the one-line rationale attached to each in §Open gaps; acceptance requires the orchestrator or the user, not this agent. Preferred path: one more supplement cycle applying R1–R6 (all six are plan-text edits to a single file, none touch the design). If accepted as-is instead, EXECUTE may proceed provided E-11, E-12 and E-13 are carried verbatim — they encode everything H1 and N1 would have fixed.

---

## Autonomous Goal Block

```
SESSION GOAL: Reveal display policy v2 — server-decided display_mode (map/country/none) across all three canary clients, behind location_reveal_enabled (default OFF).
Charter + umbrella plan: N/A — single plan (process/features/onboarding-canary/active/reveal-display-policy_17-08-26/reveal-display-policy_PLAN_17-08-26.md)
Autonomy: PVL supplement cycles run without approval. Validate gate is CONDITIONAL at cycle 3 (0 FAILs). EXECUTE is authorised ONLY after the orchestrator or the user accepts the two recorded CONCERNs (H1 stale integration baseline + missing baseline-first step; H2 two stale gate-table sentences) — the validate-agent did not self-accept. Preferred: one more supplement cycle applying R1-R6, all plan-text edits to a single file.
Hard stop conditions / safety constraints:
- Do not flip location_reveal_enabled. It stays False; flipping it is a separate human operator action after the real-network matrix passes.
- Do not touch apps/pixel/src/tracker.js, identity_resolver.py, is_emailable_identity, classify_org_kind, resolve_geoip's frozen 2-tuple signature, routers/events.py, or any Alembic migration.
- Do not add a migration. shown is JSONB. Scope the check to this plan's own changed-file set — the worktree is legitimately dirty from sibling sessions.
- Do not modify apps/api/services/geoip.py::_mock_geo — Section E is pre-answered (mock already lands on the map path via kind="company").
- Never use `which docker`. Detect containers with: lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'
- Do not mark anything VERIFIED on flag-OFF evidence alone. No gate at any tier exercises the flag-ON path.
- Do not delete the accuracy circle at apps/web/src/components/onboarding/canary-map.tsx:167-168 — it is required in map mode and no gate catches its removal.
- Do NOT touch apps/web/public/beam/onboarding-steps.js:155-160 — that is the head of formatNetwork including its fabrication guard. The formatConfidenceNote range is :144-154 ONLY.
- After editing onboarding-steps.js, grep it for confidenceNote and require zero hits — a leftover :467 interpolation is a ReferenceError that kills the public reveal card.
- Never restore an IP-bearing caption to satisfy e2e assertion onboarding-canary.spec.ts:214 — delete that stale assertion instead (D6). The caption was removed at commit 3e2ddb5.
- Do not trust the plan's "537" integration baseline (661 collected as of cycle 3). Re-measure in-session.
- pg_type/CREATE TYPE ENUM errors on :5433 mean a concurrent session holds the shared dev DB (check: ps aux | grep [p]ytest). That is contention, not a regression, and never grounds to punt a gate.
Next phase: supplement cycle 3 applying R1-R6, then re-validate from V1 — OR explicit acceptance of H1/H2 followed by EXECUTE Sections A -> I in order, gates per section.
Validate contract: inline in plan (## Validate Contract) — Gate: CONDITIONAL, not yet accepted
Execute start (once accepted): .venv/bin/python -m pytest tests/unit -m unit -q | .venv/bin/python -m pytest tests/integration/test_onboarding_canary_api.py -q | cd apps/web && npm run test && npm run lint | e2e spec: apps/web/e2e/onboarding-canary.spec.ts (baseline + :214 deletion FIRST) | probe scenario: real VPN + real mobile hotspot | high-risk pack: no
```
