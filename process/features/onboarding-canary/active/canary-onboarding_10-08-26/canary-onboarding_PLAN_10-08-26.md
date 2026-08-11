# Canary onboarding — conversational rebuild + location reveal

## Context

Beam's onboarding exists twice, and both copies are worse than the sum.

The **legacy static funnel** (`apps/web/public/beam/onboarding-app.js` + `onboarding-steps.js`, 928 lines of vanilla JS) has the good narrative: a pixel-art mascot chats you through 13 steps, tells you to go browse getbeam.fyi, plays a radar animation while it listens, then replays the pages you just read and asks *"is this you?"*. But it ships a hard-coded `data-site="YOUR_SITE_ID"` snippet ([onboarding-steps.js:283](apps/web/public/beam/onboarding-steps.js#L283)), **fakes** the detection for real sites (`setTimeout(advance, 3600)` at [:351](apps/web/public/beam/onboarding-steps.js#L351)), discards the "not quite" feedback it collects ([:512-521](apps/web/public/beam/onboarding-steps.js#L512)), and reimplements Clerk signup by hand in ~230 lines.

The **React dashboard flow** (`apps/web/src/app/dashboard/onboarding/page.tsx`) is the real one — real `createSite`, real snippet, real platform detection — but its mascot chat is 3 scripted lines before it hands off to a form. All the magic got dropped in the port.

We are rebuilding the conversational flow in React and replacing the weakest beat — a text profile card — with a **canarytokens-style location reveal**: a real Leaflet map, a pulsing pin on the user's city, the network they're on, and the pages they just read on getbeam.fyi. Beam's pixel is already live on Beam's own marketing site (`site_90a488f43eac`, [index.html:1680](apps/web/public/beam/index.html#L1680)), so this is a genuine catch, not a simulation.

**Outcome:** a new user sees Beam work on themselves within ~60 seconds of landing in the dashboard, before being asked to install anything.

**Locked decisions (user):** React inside the dashboard · Leaflet + OSM tiles · reveal = map pin + city/country + ISP-or-company (no raw IP, no fingerprint, no person name) · full rebuild including the dead feedback wiring.

---

## The moment

New `STEP_ORDER` (8 steps, down from 13):

```
welcome → canary_go → canary_listen → canary_reveal → confirm → site → install → done
```

The canary runs **first**, before site creation. Legacy demanded a URL and a pixel install before showing value; getbeam.fyi already carries the pixel, so the aha costs the user zero setup.

1. **`canary_go`** — *"before you install anything, let me show you what beam does. i'm going to catch you."* Primary button opens `https://getbeam.fyi/?beam=canary` in a new tab (`?beam=canary`, not the legacy `?beam=demo`, so onboarding traffic is separable in the events table). Ghost button: *"skip, i'll just install"*.
   **Compute the fp2 fingerprint on this click**, not lazily inside the poll — a backgrounded tab can perturb the canvas probe.

2. **`canary_listen`** — the radar (existing `.ob-listen`/`.ob-radar` CSS survives verbatim) with a status line escalating on a ticker: 0-8s *"listening…"* → 8-25s *"open a page on getbeam.fyi…"* → 25-60s *"still listening — did the tab actually load?"* → 60-90s *"one more moment…"*. Escape hatch throughout.

3. **`canary_reveal`** — *"got you."* then the card:
   - Leaflet map, `zoom: 11`, pulsing `divIcon` dot, translucent accuracy circle.
   - `Hanoi, Hanoi · VN`
   - `Viettel Group · your ISP` (or `Acme Inc · your company network`)
   - The page list: path + seconds, ported from `renderJourney` ([onboarding-steps.js:81-95](apps/web/public/beam/onboarding-steps.js#L81)).
   - **Honesty caption, load-bearing:** *"that's an IP-level estimate — usually the right city, sometimes the wrong suburb."* Without it a 30km-off pin reads as "your product is broken", which is the #1 failure mode of a map reveal.

4. **`confirm`** — *"is this you?"* → `✓ yes, that's me` | `not quite` → a real form that actually posts (§Feedback).

**Never fake it.** Legacy's non-sample branch claimed a detection it never made. If nothing lands, say so.

---

## Architecture decision: geo comes from the caller's IP, journey comes from the DB

The two halves of the reveal have different data paths, and keeping them separate is what makes this safe:

| Half | Source | DB read? |
|---|---|---|
| **Where you are** (pin, city, network) | `resolve_client_ip(request)` — the caller's own IP | **No** |
| **What you did** (page list) | fingerprint join, scoped to Beam's own site | Yes |

Consequences:
- Geo is **never** read from the matched `Visitor.ip_address`. A fingerprint collision can therefore never disclose someone else's location — the only IP involved is the requester's own.
- The map **is not gated on the visit landing**. Adblocker / DNT / VPN users still get a reveal (see degraded paths).
- The journey query gets a `site_id == settings.beam_self_site_id` predicate that `demo_journey` lacks ([demo.py:314](apps/api/routers/demo.py#L314) matches `Visitor.fingerprint` with **no site scoping** — cross-tenant by construction). This is the anti-regression for commit `7e798ab` ("close cross-tenant PII leak on /demo").
- No coordinates are persisted anywhere. Nothing downstream consumes them, and adding a household-adjacent coordinate to every pageview row would be a material privacy expansion buying nothing.

---

## Backend

### `apps/api/services/geoip.py` — widen, don't replace

Current state ([geoip.py:46](apps/api/services/geoip.py#L46)): `fields=status,countryCode,regionName`. ip-api's `/json/{ip}` returns `city`, `lat`, `lon`, `timezone`, `isp`, `org`, `as` in the **same request** — the 45/min ceiling counts requests, not fields. Zero extra cost.

The decisive argument is caching, not the mask: `resolve_geoip` is already called synchronously by `/ingest` ([events.py:366-373](apps/api/routers/events.py#L366)) for the getbeam.fyi visit **seconds before** the chat asks. In the happy path the reveal makes **zero** outbound calls — it reads the cache line ingest just wrote.

- Add `resolve_geoip_full(ip) -> GeoResult | None` (dataclass: `country_code, region, city, lat, lon, isp, org, as_str`).
- Make the existing `resolve_geoip(ip) -> tuple[str, str]` a **thin wrapper** over it. Signature and return unchanged → `events.py` needs zero edits, behaviour byte-identical. This is the single most important backward-compat property; test it explicitly.
- **New Redis prefix `geoip2:` with a JSON value.** Do NOT overload `geoip:`, whose value is the pipe-joined `"US|California"` ([:61](apps/api/services/geoip.py#L61)). A rolling deploy where an old pod reads a new-format value under the old key silently corrupts `country_code` on every ingested event.
- **Add the missing mock branch.** `geoip.py` has no `settings.mock_external_apis` short-circuit today — a repo-wide rule violation (`content_reader.py:262` and `enricher.py:568` follow it). Return a deterministic fake.
- **Handle 429.** Only `status_code == 200` is handled today, so a rate-limit reply silently degrades. Read `X-Ttl`, set a short Redis backoff key, skip the provider until it expires.

### `apps/api/routers/onboarding.py` — new, authed

`POST /api/v1/onboarding/canary`, mounted at `prefix="/api/v1/onboarding"` in `apps/api/main.py` beside the demo router (~:551).

```
auth:   Depends(get_current_user)
limit:  @limiter.limit("30/minute")     # NOT 12 — see poll cadence below
budget: none — no paid provider is called
flag off → 404 (dormant, not revealed — the agent_fetch_beacon_enabled posture)

body: { fingerprint: "fp2_..." }

200:
{
  "landed": true,
  "pages":   [{ "path": "/pricing", "title": "…", "seconds": 42, "at": "…" }],
  "geo":     { "lat": 21.03, "lng": 105.85, "accuracy_km": 25,
               "city": "Hanoi", "region": "Hanoi", "country_code": "VN" } | null,
  "network": { "label": "Viettel Group", "kind": "isp" } | null
}
```

- **The IP is never in the response.** Log it truncated (`ip[:8]`), as the rest of `demo.py` does. This is a deliberate divergence from `/demo/identify`, which returns the full unredacted IP.
- Use `apps/api/services/ip_resolution.py::resolve_client_ip` — **not** `demo._client_ip` ([demo.py:77-81](apps/api/routers/demo.py#L77)), which reads `X-Forwarded-For` first with no trust check and is client-spoofable. With `ingest_trust_cf_connecting_ip = True` ([config.py:257](apps/api/config.py#L257)) behind CF, `resolve_client_ip` returns the real client IP.
- Extract the journey query from `demo_journey` into `apps/api/services/onboarding_canary.py` so both callers share one implementation; add the `site_id` predicate on the new path only (leave `/demo/journey`'s behaviour untouched so the static funnel keeps working).
- **Anti-regression test:** assert the 200 body has no `ip` / `site_id` / `visitor_id` / `fingerprint` key, so a future "while we're here, also return X" PR trips a test rather than a security review.

### ISP-vs-company ladder (all rungs free, first non-empty wins)

1. `asn_lookup.lookup_asn(ip)` → offline MaxMind ASN org. **Verify `settings.maxmind_asn_db_path` is actually set in prod — it defaults to `""` ([config.py:852](apps/api/config.py#L852)); if empty this rung is dead and everything falls through.**
2. ip-api `org` (usually the end org on corporate ranges)
3. ip-api `isp` (the carrier)
4. ip-api `as` → strip the `AS\d+` prefix (`company_resolver._ASN_RE:330` already does this)
5. Empty → **omit the network line entirely.** Never render "Unknown ISP"; a blank line beats an admission of ignorance in a moment whose job is to look omniscient.

Label choice via the existing `company_resolver.classify_org_kind` ([:340](apps/api/services/company_resolver.py#L340)):
- `eyeball` + org differs from isp → `"company"` → *"looks like you're on **Acme Corp**'s network"* (strongest version)
- `eyeball` otherwise → `"isp"`
- `cdn`, or `company_resolver.is_privacy_relay_ip(ip)` ([:233](apps/api/services/company_resolver.py#L233)) → `"relay"` → *"you're behind a privacy relay — this pin is the relay's exit, not you."* Honest beats wrong.
- `datacenter` → `"datacenter"` → the VPN copy.

Do **not** call `check_ip_privacy` ([:194](apps/api/services/company_resolver.py#L194)) — it needs `ipinfo_token` and a network round-trip for no display benefit.

### Config

```python
beam_self_site_id: str = "site_90a488f43eac"   # currently hardcoded in 6 static HTML files only
location_reveal_enabled: bool = False          # house-style comment block: what it gates,
                                               # why off, ROLLOUT ORDER, KNOWN LIMITATIONS
```

The widened fields mask is deliberately **not** flagged — same request, same host, only more of the reply parsed with `.get()` defaults. A flag there would mean two live parse paths in the ingest hot path, which is worse than the risk it removes.

**Rollout order:** (1) ship the mask + `geoip2:` key with the flag off, confirm `/ingest` `country_code`/`region` unchanged for a full 24h cache cycle → (2) enable in staging, eyeball the pin on residential, corporate, and mobile/CGNAT networks → (3) prod.

### Migration (one)

`add_onboarding_canary_support`:
- `Index("idx_visitors_fingerprint", "fingerprint")` — **required, not optional.** `visitors` has only `site_id` composites ([visitor.py:14-18](apps/api/models/visitor.py#L14)); every poll is currently a seq scan. Also speeds the existing `/demo/identify` and `/demo/journey`.
- `identity_feedback` table (see §Feedback).

**Migration safety:** re-derive the head live with `alembic -c apps/api/alembic.ini heads` — it moves constantly. **Pin `DATABASE_URL` to `localhost:5433` first**; a bare alembic command inherits `.env`, which points at Supabase **production**.

---

## Frontend

### Logic lives in `src/lib` — this is a hard constraint, not a preference

`apps/web/vitest.config.ts` is `environment: "node"` with `include: ["src/**/*.test.ts"]`. There is no jsdom and no testing-library. Component tests would need new deps. So every testable decision goes into a pure module:

- **`src/lib/onboarding-flow.ts`** — `StepId`, `STEP_ORDER`, `FlowState`, `FlowEvent`, `flowReducer`, `typingDelay(text, reduced)` (`Math.min(1300, Math.max(480, len*22))`, 0 when reduced), `load/save/clearFlowState`.
- **`src/lib/onboarding-script.ts`** — all copy as **data** (`Record<StepId, Line[]>`), plain strings. Interpolation happens in React. This kills the XSS shape at [onboarding-steps.js:394-407](apps/web/public/beam/onboarding-steps.js#L394), where provider-supplied `full_name`/`company_name` go into `innerHTML` unescaped.
- **`src/lib/beam-fingerprint.ts`** — verbatim fp2 port from [tracker.js:203-231](apps/pixel/src/tracker.js#L203). Export `hash128()` separately from the DOM-touching wrapper so the hash is node-testable. Comment must pin it: *byte-identical to tracker.js fp2 or the canary join silently fails.* Replaces the duplicate at [onboarding-steps.js:23-76](apps/web/public/beam/onboarding-steps.js#L23).
- **`src/lib/canary-format.ts`** — `formatPlace`, `formatNetwork`. A `datacenter`/`cdn` org must **never** render as "your company" — same fabrication guard the backend enforces at [ipinfo.py:78-84](apps/api/services/identity_providers/ipinfo.py#L78).
- **`src/lib/canary-reveal-mode.ts`** — pure `chooseRevealMode(response, tileState) → "map" | "text" | "skip"`.

### Components

```
src/app/dashboard/onboarding/page.tsx           thin shell (see "keep three things" below)
src/components/onboarding/onboarding-flow.tsx   useReducer(flowReducer) owner; imports the CSS
src/components/onboarding/chat-transcript.tsx   bot/user bubbles, mascot, typing dots
src/components/onboarding/chat-controls.tsx     button row / field / chips
src/components/onboarding/steps/*.tsx           one per step
src/components/onboarding/canary-listen.tsx     radar + the poll
src/components/onboarding/canary-map.tsx        "use client", Leaflet
src/components/onboarding/canary-reveal.tsx     map + place + network + page list
src/components/onboarding/identity-feedback-form.tsx
src/components/onboarding/use-message-queue.ts | use-auto-scroll.ts | use-reduced-motion.ts
src/styles/onboarding-chat.css
```

**Message queue** — one effect keyed on the step with a `cancelled` flag and a cleared `setTimeout` ref. State-driven rendering means the `chatRef.innerHTML = ""` StrictMode hack at [onboarding-welcome-chat.tsx:118](apps/web/src/components/onboarding-welcome-chat.tsx#L118) disappears.

**Auto-scroll** — `ResizeObserver` replaces the legacy immediate/rAF/70ms triple-pin ([onboarding-app.js:35-40](apps/web/public/beam/onboarding-app.js#L35)), which existed for late-loading content — and map tiles are the worst case. Add what legacy lacked: **only auto-pin when already within ~80px of the bottom**, or the map yanks itself out from under a user who is panning it.

**Resume** — new key `beam_onboarding_v2` (`{v:2, step, siteId, canaryOutcome}`). Do not reuse `beam_ob_step` — legacy vocabulary would resume into dead step ids. Validate against `STEP_ORDER`, unknown → `welcome`, **never resume into `canary_listen`** (a 90s deadline can't be resumed) → resume to `canary_go`. Keep writing `beam_onboarded_v1`; [dashboard/page.tsx:351](apps/web/src/app/dashboard/page.tsx#L351) depends on it.

**Chrome** — render inside the layout's `<main>`; drop the `fixed inset-0 z-60` overlay so the layout's single "Exit to dashboard" ([layout.tsx:565](apps/web/src/app/dashboard/layout.tsx#L565)) stops being covered by a duplicate. 8 progress dots, not 13, not 2.

### Polling

TanStack, on the pattern at [campaigns/[campaignId]/page.tsx:129-136](apps/web/src/app/dashboard/campaigns/[campaignId]/page.tsx#L129), with three necessary deviations:

```ts
refetchInterval: (q) => q.state.data?.landed || expired ? false
                        : (elapsed < 20_000 ? 2000 : 4000),
refetchIntervalInBackground: true,   // MANDATORY
refetchOnWindowFocus: true,
staleTime: 0, gcTime: 0, retry: false,
```

- **`refetchIntervalInBackground` is the deviation that matters.** The dashboard tab is *hidden* — the user is in the other tab, which is the entire point. Default TanStack stops polling on a hidden tab; a naive port silently never lands. `refetchOnWindowFocus` then fires an instant refetch the moment they tab back, which is exactly when they're looking.
- **Deadline 90s.** Legacy's 15s ([onboarding-steps.js:333](apps/web/public/beam/onboarding-steps.js#L333)) is far too short for open-tab → read → return. Driven by a 1s ticker so the interval callback re-evaluates `expired`.
- **Cadence vs rate limit — a real bug the naive port would ship.** 2s × 90s = 45 calls against a `12/minute` limit → 429 mid-reveal. Fixed on both sides: back off 2s→4s after 20s (≈27 calls) **and** set the new endpoint to `30/minute`.
- Unmount: `enabled` flips false on step change; `gcTime: 0` drops the cache; the ticker clears in its effect cleanup; the queryFn `signal` propagates (`api.request` forwards a caller-supplied `init.signal` — [api.ts:229](apps/web/src/lib/api.ts#L229)).

### Leaflet

- `leaflet@^1.9` + `@types/leaflet`. **Skip `react-leaflet`** — it adds a dependency and a React-version coupling to save ~40 lines of imperative `useEffect`. (If it is used anyway: repo is React 18, so pin **v4** — v5 requires React 19.)
- **Two independent SSR guards:** parent imports via `next/dynamic(..., { ssr: false })`, *and* `const L = (await import("leaflet")).default` happens **inside `useEffect`**, never at module scope.
- **`L.divIcon`, not `L.marker`.** Leaflet resolves the default icon's PNG relative to the stylesheet and it 404s under bundlers — the classic broken-marker bug. A 12px dot with two CSS-animated rings is both the fix and the desired aesthetic, and reuses the radar pulse already in `onboarding.css`.
- Tiles `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` in a **single exported constant** so a keyed provider is a one-line swap. **Attribution is mandatory** under the OSM Tile Usage Policy — do not CSS-hide the control. Constrain: `scrollWheelZoom: false`, `minZoom: 9`, `maxZoom: 13`, `dragging: true`. **Never zoom past ~13** — that makes a precision claim the data cannot support and converts a wow into "that's wrong".
- **CSP: verified clear.** No CSP anywhere in `apps/web` — `next.config.mjs` `headers()` only sets `Cache-Control`/`Vary` for `/blog`, there is no `apps/web/middleware.ts`, and `public/beam/index.html` has no CSP `<meta>`. Leave a comment by the tile constant noting a future CSP needs the tile host in `img-src`.
- **Tile privacy:** the request tells OSM the user's IP, UA, referer, and the area being viewed — but that area *is* the IP-derived location, which OSM could geolocate itself. Marginal leak ≈ zero. Do **not** proxy tiles through the API to "fix" this; it puts Beam in the tile-serving business and likely violates OSM's bulk/proxy prohibition.
- Bundle ~42KB gz + 4KB CSS. Run `npm run build` in `apps/web` after adding and confirm shared First Load JS is unchanged and leaflet appears only in the onboarding route chunk.

### The 25KB `.ob-*` CSS

`onboarding.css:6-33` contains `:root`, `* { box-sizing }`, `html, body` and `body` rules — that is why [onboarding-welcome-chat.tsx:104](apps/web/src/components/onboarding-welcome-chat.tsx#L104) injects it at runtime instead of importing it.

**Copy it to `src/styles/onboarding-chat.css` and import from `onboarding-flow.tsx`** (App Router bundles + hashes plain CSS imports; no FOUC). During the copy: delete lines 6-33 and re-declare the custom properties scoped under `.ob-root`; delete selectors for dropped steps (`.ob-plan*`, `.ob-toggle`, `.ob-auth-*`, `.ob-draftcard`, `.ob-dash*`, `.ob-checklist`) — should land near 12KB. Add `.ob-map*`. Load Fraunces + DM Mono via `next/font/google` instead of the runtime Google `<link>` at [:110](apps/web/src/components/onboarding-welcome-chat.tsx#L110).

Since the reveal renders inside the cream chat theme, **dark-mode tile handling is moot** — skip it.

### Mascot sprites: three → two, not one

`public/beam/onboarding-mascot.js` must stay a plain `<script>` (the static landing page calls `window.beamMascot()` and cannot import from `src/`). Keep it as the marketing copy; make `src/components/beam-mascot.tsx` the single React sprite with a `palette?: "tour" | "chat"` prop; **delete `onboarding-welcome-chat.tsx` entirely** — it is copy #3, and deleting it also removes the runtime `<link>` injection, the `innerHTML` StrictMode hack, and the `dangerouslySetInnerHTML` at [:181](apps/web/src/components/onboarding-welcome-chat.tsx#L181). Cross-reference comments in the two survivors so the grid stays in sync.

### Keep three things when thinning `page.tsx`

1. The `?site=&step=install` resume branch ([:56-70](apps/web/src/app/dashboard/onboarding/page.tsx#L56)) — a real feature.
2. The `?welcome=1` distinction ([:29](apps/web/src/app/dashboard/onboarding/page.tsx#L29)) — with it, run the chat; without it, existing users clicking "Add site" get the bare form.
3. **The cross-tenant disclosure block ([:286-309](apps/web/src/app/dashboard/onboarding/page.tsx#L286))** — a compliance requirement with a live e2e assertion on `[data-testid="cross-tenant-disclosure"]` and the literal string `cross-tenant identity`. Do not lose it in the rewrite.

---

## Feedback ("not quite")

Today the four checkboxes and textarea are built and the submit handler is `() => ob.answer('sent you some feedback','walk')`. The DOM is read zero times.

New `identity_feedback` table (in the same migration): `id`, `user_id`, `site_id?`, `fingerprint?`, `surface` (`"onboarding_canary"`), `shown` JSONB (exactly what we rendered: city/region/country/org/kind/rounded lat-lng), `reasons` (string[]), `note` (Text, truncated 500), `created_at`.

**Reasons rewritten for what is now on screen:** `wrong_city`, `wrong_network`, `vpn_or_proxy`, `not_me`. The legacy set (wrong name / wrong company / wrong socials) describes a profile card that no longer exists at this beat.

`POST /api/v1/onboarding/identity-feedback` — authed, validate reasons against a frozenset, truncate, insert, 204. UI uses native `<input type="checkbox">` styled with the existing `.ob-check` CSS (there is no shadcn checkbox and adding one for four boxes is the wrong trade). Submit is **optimistic** — fire the POST, advance immediately, swallow failures; never block onboarding on a feedback write. Acknowledge specifically: *"noted — 'wrong city' goes straight to the team that tunes IP geo."*

This is the identity waterfall's first precision signal; `vpn_or_proxy` reports cross-checked against `check_ip_privacy` give a cheap accuracy metric. **This is the one droppable piece if scope needs cutting** — the index migration is still required either way.

---

## Degraded paths

| Condition | Response | UI |
|---|---|---|
| Visit lands, geo present | full | map + place + network + page list |
| Visit lands, geo missing | `geo: null` | page list only, no map |
| **Visit never lands, geo present** | `landed: false`, geo present | *"didn't catch your visit — adblocker, DNT/GPC (we honor both), or the tab never loaded. but here's what your IP alone says:"* + map. **Do not fake a detection.** |
| Neither | both null | skip to `site`, one honest line |
| geo `("","")` or provider exception | `reason: provider_unavailable` | skip the map. **Never render at 0,0** — Null Island is the classic version of this bug |
| lat/lng missing, city present | `geo: null`, city in `network`-adjacent copy | text-only reveal; a partial reveal is still decent |
| Private/localhost IP (dev) | `private_ip` — already short-circuited at [geoip.py:24](apps/api/services/geoip.py#L24) | `MOCK_EXTERNAL_APIS=true` returns a deterministic fake so it demos locally |
| **VPN / proxy / datacenter IP** | `network_kind: datacenter\|relay`. Their *visit* was silently 204'd ([events.py:307-310](apps/api/routers/events.py#L307)) and never stored — but geo doesn't read the visit, so the map still works | *"you're on a VPN — here's where it **thinks** you are."* Turns a failure into a second wow. **Critically: the map must not be gated on the visit, or this whole cohort gets nothing.** |
| Consent-gated EU visitor | **Non-issue today** — [index.html:1680](apps/web/public/beam/index.html#L1680) has no `data-consent`, so `CONSENT_MODE` defaults `"off"` and `GATED` is false ([tracker.js:490,507](apps/pixel/src/tracker.js#L490)) | unaffected. Risk note: adding `data-consent="eu"` later breaks the journey half for EU users |
| `do_not_resolve` (GPC/DNT) | Not reachable — geo reads no row, and the journey query is a plain visitor read | **Fire the reveal.** `do_not_resolve` gates *third-party identity resolution* ([identity_resolver.py:548](apps/api/services/identity_resolver.py#L548)); the promise is "don't ask outside vendors who I am". Showing a user their own city, computed from a GeoIP call we already make unconditionally at [events.py:370](apps/api/routers/events.py#L370), breaks none of it. Do not add a lookup purely to enforce it. |
| ip-api 429 | `provider_unavailable` + backoff key | as above. Near-unreachable in practice — ingest warmed the cache seconds earlier |
| **Tile host blocked** (corporate firewall, uBlock) | n/a, client-side | Count `tileerror` events: ≥4 within 2.5s of init, or no `load` within 4s → destroy the map, swap to the text reveal. **Most likely visible field failure** — a grey box with a floating pin is worse than no map |

---

## Legacy static funnel

**Keep it, change nothing about it in this pass.** `next.config.mjs:53-61` rewrites `/onboarding` → `/beam/onboarding.html` in `beforeFiles`, which means `src/app/onboarding/page.tsx` is almost certainly dead (the rewrite intercepts first) — but confirm before deleting it; it is the fallback if the rewrite is ever removed.

Deleting the funnel would 404 every marketing CTA and remove the only **logged-out** demo surface, a job the new flow structurally cannot do since it lives behind auth. Follow-up (not now): truncate it to `welcome → canary_go → canary_listen → canary_reveal → "create your account"` handing off to `/sign-up`, deleting `install`/`detect`/`sample`/`paywall`/`account`/`dash` — roughly 600 of its 928 lines — and have it call a public unauthed twin of `/canary` sharing `onboarding_canary.py`.

---

## Risks

1. **`maxmind_asn_db_path` / `ipinfo_token` may be empty in prod** ([config.py:852,856](apps/api/config.py#L852) both default `""`). If the ASN rung is dead everything falls to ip-api's `org`/`isp`. **Verify the deployed env before shipping copy that promises a network line.**
2. **Client IP correctness in prod** — highest-consequence correctness item. If `resolve_client_ip` degrades to the Cloudflare edge IP, every pin lands in a CF datacenter and the feature looks broken rather than degraded. Confirm on staging by comparing the returned city against a known network.
3. **Adblockers / DNT / GPC.** Beam's audience is technical founders; a large share will hit the timeout branch. Consider a pre-flight `HEAD` on the tracker URL and, if blocked, skip the canary with *"your ad blocker is eating our pixel — respect. skipping the demo."*
4. **Safari canvas randomization — largely mitigated.** Safari randomizes canvas readback per-origin, and `canvasFp()` is inside fp2 ([tracker.js:203](apps/pixel/src/tracker.js#L203)). But `/` and `/dashboard` are the **same Next.js app on the same origin** (verified in `next.config.mjs`), so both tabs compute the same seed. Still worth one Safari pass; if it breaks, the timeout branch is the Safari experience and must not look like a bug.
5. **Geo precision.** IP pins are city-level at best and often land on the ISP's registered centroid — on mobile CGNAT, a different city entirely. The accuracy circle and the honesty caption are the mitigation, not optional polish.
6. **ip-api.com's free tier is plaintext HTTP and its terms restrict non-commercial use.** It is *already* in the production ingest path; this promotes it to a user-facing moment, widening existing exposure. Re-check current terms. Migrating to a local MaxMind GeoLite2-City DB (same shape as `asn_lookup.py`) removes both the terms question and the 45/min ceiling — the intended follow-up, not this change.
7. **OSM tile policy** discourages heavy commercial use. Onboarding volume is low; keep attribution and plan a keyed host if this ever broadens.

---

## Verification

**Unit (backend, `tests/unit/`)** — extend `test_geoip.py` (existing patterns: `patch("apps.api.services.geoip.httpx.AsyncClient")`, `_geoip_cache.clear()`):
- **Backward compat, the important one:** same mocked payload → `resolve_geoip("8.8.8.8")` still returns exactly `("US", "California")`.
- Widened mask present in outgoing `params["fields"]`; `resolve_geoip_full` maps each field.
- Cache migration: a stale legacy `geoip:` value `"US|California"` must not be mis-parsed or crash.
- 429 → degraded + backoff key set; a second immediate call constructs no client.
- Mock mode → deterministic fake and **zero** HTTP (`patch(..., side_effect=AssertionError)`).
- New `test_location_reveal.py`: network ladder rung-by-rung, all-empty omits the field, `classify_org_kind` → `network_kind` mapping, degraded reasons for private IP / empty geo / `lat==lng==0.0`.

**Integration (needs Docker — Postgres `localhost:5433`, Redis DB 15 per `tests/conftest.py`)** — new `test_onboarding_canary_api.py`:
- Flag OFF → 404, no provider call. Flag ON unauthenticated → 401.
- Authed + mocked geo → 200 full shape.
- **Anti-regression:** body contains no `ip`/`site_id`/`visitor_id`/`fingerprint` key.
- **Site scoping:** a fingerprint matching a visitor on *another* site returns `pages: []`.
- Provider failure → 200 degraded, never 500. Rate limit: 31 rapid calls → 429.
- Cache reuse: two calls → exactly one `httpx` call (proves the "ingest warmed it" claim).
- `tests/integration/test_events_ingest.py` must stay green — it is the regression net for the `resolve_geoip` wrapper.
- Migration smoke: `idx_visitors_fingerprint` exists after upgrade.

**Frontend unit (vitest node, no new deps)** — `onboarding-flow.test.ts` (STEP_ORDER integrity, every transition, retry-once, persistence round-trip, **resume never lands on `canary_listen`**, unknown stored step → `welcome`, `typingDelay` clamps), `beam-fingerprint.test.ts` (fixed component array → exact hash string, with the "changing this breaks the pixel join" comment), `canary-format.test.ts` (never attributes a datacenter org to the user), `canary-reveal-mode.test.ts`.

**Playwright (`apps/web/e2e/onboarding-canary.spec.ts`)** — **the Clerk gap does not block this.** `playwright.config.ts:60` blanks `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `e2e/auth.setup.ts` logs in via `POST /api/v1/auth/login` as `demo@getbeam.fyi` with a legacy JWT, and both `src/middleware.ts:20` and `dashboard/layout.tsx:531` honour that path. Authed dashboard legs run today. (Genuinely unharnessed: `ClerkTokenGate`, Clerk token refresh, orgs — so read the user's name through the existing nullable `src/lib/use-auth-safe.ts` and degrade to "hey".) Confirm `demo@getbeam.fyi` is seeded before relying on this.

Mock `**/api/v1/onboarding/canary` with `page.route`, **answering OPTIONS with CORS headers** per the established pattern at `onboarding.spec.ts:59-76` (the dashboard calls :3000 → :8000 cross-origin; without it the mock silently fails). Also route `**/tile.openstreetmap.org/**` to a 1×1 PNG so CI does no third-party I/O. Legs: `canary_go` opens the right URL (stub `window.open` via `addInitScript`) · landed-on-2nd-poll → reveal shows city + org · timeout → honest copy and **no map node** · "not quite" → `waitForRequest` asserts the checked reasons in the POST body · skip → lands on `site` · **regression: the AC-9 `cross-tenant-disclosure` assertion still passes** · `emulateMedia({reducedMotion:"reduce"})` → all lines immediate, no confetti.

**Manual QA before flipping the prod flag** (not automatable — needs the real pixel, real DB, and a shared fingerprint): corporate VPN, mobile hotspot (worst-case accuracy), uBlock-enabled browser (tile fallback), and one Safari pass.

---

## Suggested phasing

1. **Backend, flag off** — `resolve_geoip_full` + `geoip2:` key + mock branch + 429 handling; migration (index + feedback table); `onboarding_canary.py`; `routers/onboarding.py`; config. Soak the geoip change 24h, confirm `/ingest` unchanged.
2. **React chat shell** — the `src/lib` modules, the flow reducer, transcript/controls, welcome + site + install + done wired to the existing real `api.createSite` / `PixelInstallGuide`. Delete `onboarding-welcome-chat.tsx`. At this point the flow is a strictly better version of what ships today, with no canary.
3. **The canary** — `canary_go` / `canary_listen` / `canary_reveal` / `confirm`, Leaflet, feedback form. Flag on in staging.
4. **Follow-ups** — truncate the static funnel; MaxMind GeoLite2-City to drop ip-api; surface the feedback counts in ops.
