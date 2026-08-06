# Beam Lab — Resume Notes

Last updated: 2026-08-01 · Evergreen handoff for the Beam Lab AI-agent detection experiment.

- **Team presentation (plain language + diagrams):** [beam-lab-team-brief.md](./beam-lab-team-brief.md)
- Full technical detail (VI): [agent-detection-architecture.md §5d](./agent-detection-architecture.md#5d-soft-serve-gate--marker-biên-_bfm-trên-beam-lab-31-07--01-08)

This doc is the short English pointer for picking eng work back up.

## What Beam Lab is

A standalone static site, **not** part of the multi-tenant `apps/api` product surface, used to
validate the AI-agent detection chain end-to-end on a domain Beam fully controls.

| Item | Value |
|------|-------|
| Site | https://beamlab.nhantown.com/ |
| Cloudflare Pages project | `beam-lab` |
| Site ID | `site_16c46453546f` |
| Pixel destination | `beam-dev.nhantown.com` (3-path locked-down host) |
| Fetch beacon destination | `beam-api.nhantown.com` (full API host) |
| Database | Local Docker Postgres `retarget_agent` — **not** production |
| Content canary | `FUCHSIA-0731` on the homepage — proves an AI answer is reading the live page, not a stale cache/index copy |
| Deep pages | `/tac-nhan/` (full UA token list), `/kiem-chung/{openai,anthropic,perplexity,khac}/` |
| Latest noted production deployment UUID | `9a4d1f20-6bdd-46fc-bfc5-447c83e81cab` (for `wrangler pages deployment tail`) |

## Key files

| Path | Role |
|------|------|
| `infra/cloudflare/beam-lab/functions/_middleware.js` | Pages Functions middleware: soft-serve gate, `_bfm` marker mint + stamp, full-log capture, beacon POST |
| `infra/cloudflare/beam-lab/wrangler.toml` | `BEAM_API_BASE`, `BEAM_SITE_ID`, `BEAM_FULL_LOG`, `BEAM_AGENT_GATE` vars (`BEAM_FETCH_BEACON_SECRET` is a wrangler secret, not in this file) |
| `infra/cloudflare/beam-lab/public/index.html`, `tac-nhan/`, `kiem-chung/*/` | Static lab pages + pixel snippets |
| `apps/api/services/agent_fetch_beacon.py` | Classifies + persists the beacon POST from the edge |
| `apps/api/services/agent_marker.py` | `_bam` (API Fernet) mint/decode **and** `_bfm` (edge hex) extraction (`edge_marker_from_url`) |
| `apps/api/services/agent_visit_persistence.py` | Writes `agent_fetch_events.link_marker` |
| `apps/api/routers/events.py` | Reads `_bfm` off pageview URLs into `events.link_marker` |
| `apps/api/migrations/versions/f3c8b2e91d47_*.py` | `agent_fetch_events.link_marker` (dev Postgres only) |
| `apps/api/migrations/versions/a7d419e6c052_*.py` | `events.link_marker` (dev Postgres only) |

## Plans (reconciled 07-08-26)

Both plans have been moved to `process/features/evallayer/completed/` and their `status:`
frontmatter corrected via a UPDATE PROCESS pass. Neither file was deleted.

- `agent-gate-lab_31-07-26/` — the original hard-403 gate, `status: superseded`. **Rejected by
  reality**: real ChatGPT-User hit the 403 twice, sent no headers, never checked in, and told its
  user the page was unreadable, so it served a stale answer instead. Kept for design history.
- `agent-gate-soft-serve_31-07-26/` — `status: shipped-with-known-gaps`. Supersedes the above
  **behaviourally** (the hard-403 file was not deleted). Always 200 + full HTML; the
  identification ask moves inside the page as an HTML comment via `HTMLRewriter`, and no
  `x-agent-gate` response headers are set on the human/identified path. Confirmed committed
  (`74e85b1`) and present in `_middleware.js`; the live Cloudflare deployment's running code was
  **not** independently re-fetched/diffed in this reconciliation pass — treat deploy/repo parity
  as UNVERIFIED-BUT-ASSUMED, not confirmed-live-tested today.
- Open items (TTL policy, human click-through, pending migrations, `BEAM_FULL_LOG` still on,
  Gemini-via-AWS-fetcher gap, ChatGPT browse intermittency) are now tracked as an explicit backlog
  note, not left implicit in this doc:
  `process/features/evallayer/backlog/beam-lab-soft-serve-known-gaps_NOTE_07-08-26.md`.

## Two markers — do not confuse them

| | `_bam` (API, product) | `_bfm` (edge, Beam Lab only) |
|---|---|---|
| Minted by | `apps/api/services/agent_marker.py` (Fernet, encrypted) | `_middleware.js` (`crypto.randomUUID()`, 12 hex chars) |
| Decodable | Yes → `agent_fetch_events.id` | No — opaque lookup key, matched by string equality only |
| Stamped onto | `offer.url` entries in `offers.json`, gated by `agent_marker_enabled` | Every same-host `a[href]` in lab HTML, gated by `BEAM_AGENT_GATE` (a Cloudflare Pages env var, not an `apps/api/config.py` flag) |
| Verified end-to-end with real ChatGPT | Yes, 2026-07-31 (see architecture doc §5b) | Edge → agent → link-preserved-in-answer verified 31-07; **human click-through not yet verified** |

## Env vars for this experiment

| Var | Where | Purpose | Current value |
|-----|-------|---------|----------------|
| `BEAM_AGENT_GATE` | `wrangler.toml` `[vars]` | Kill switch for the gate. Only the literal `"0"` disables it | `"1"` |
| `BEAM_FULL_LOG` | `wrangler.toml` `[vars]` | Logs the complete request/response of every non-static visitor (human included) | `"1"` — **turn off after the debug window** |
| `BEAM_FETCH_BEACON_SECRET` | wrangler secret (`wrangler pages secret put`) | Must match the API's own `BEAM_FETCH_BEACON_SECRET` or every beacon 401s | secret, not in repo |

Deploy: `npx wrangler pages deploy public --project-name beam-lab` from
`infra/cloudflare/beam-lab/`. Tail production logs:
`npx wrangler pages deployment tail --project-name beam-lab`.

## Findings this session (2026-07-31 → 2026-08-01)

- **ChatGPT browse is intermittent**, not broken: canary-only / homepage fetches usually succeed
  and quote `FUCHSIA-0731` correctly. Whether it *hops* to a linked deep page varies by prompt
  wording — "answer using only the loaded page" reliably suppresses the hop even when the link is
  right there in the fetched HTML.
- Given a **direct** deep-page URL, ChatGPT sometimes does not fetch at all, invents an excuse, or
  cites the wrong host (`amlab.vn`) — even though the page is public HTTP 200.
- Pasting the page's HTML/text directly into chat gets a correct, complete answer (11/13 UA tokens
  recognized, 2 intentionally not: `google-extended`, `applebot-extended`) — content comprehension
  is solid; **active browsing** is the unreliable part.
- **IP is not a session key.** Azure/OpenAI-origin IPs (ASN 8075) rotate between fetches *within
  one* ChatGPT answer, so IP cannot be used to correlate two fetches from the same conversation —
  only the marker can.
- One fetch matched a Gemini eval window but used UA `got (https://github.com/sindresorhus/got)`
  on ASN 14618 (Amazon, Ashburn) — not `Googlebot` / `google-cloudvertexbot`. The classifier does
  not treat `got` as an AI token, so **no** `agent_fetch_events` row was written. Product gap if
  Gemini-via-AWS-fetcher traffic needs tracking.
- Deep pages (`/tac-nhan/`, `/kiem-chung/*/`) initially shipped without the pixel snippet — fixed;
  end-to-end handoff on those specific pages is not yet re-verified.
- Schema.org `@graph` on the homepage: `Organization`, `WebSite`, `SoftwareApplication`, `WebPage`,
  `FAQPage`. A `TechRetail`/`TechArticle` experiment was tried and removed (Rich Results treated it
  as noise). The agent gateway link stays on `<link rel="alternate">`, not `Organization.url`.

## Open items, in priority order

1. Retest the ChatGPT hop with a natural prompt (no "don't leave the page" instruction), or accept
   browse intermittency as the final finding for now.
2. Get a real human to click a `_bfm=`-marked link and confirm the `events.link_marker ↔
   agent_fetch_events.link_marker` join fires correctly (the `_bam` path already has this proof;
   `_bfm` does not yet).
3. Optional product work: classify Gemini-like `got`/AWS-hosted fetchers so they are not silently
   dropped.
4. Apply the two `link_marker` migrations (`f3c8b2e91d47`, `a7d419e6c052`) to the production API —
   today they exist only in the local dev Postgres used for the lab.
5. Decide a TTL policy for `_bfm` (it has none today, unlike `_bam`'s 7-day Fernet expiry); run
   on-demand tests against Perplexity and Claude.
6. Turn `BEAM_FULL_LOG` back off once the current debug window is done — it logs every visitor,
   not just AI ones.
7. F14 Web Bot Auth (RFC 9421) remains open; unrelated to this session's work.
8. ~~Run a UPDATE PROCESS pass to reconcile the two plan files' `status: awaiting-execute-approval`
   against the fact that soft-serve behaviour is already live on the lab deployment.~~ **Done
   07-08-26** — see `## Plans (reconciled 07-08-26)` above and
   `process/features/evallayer/backlog/beam-lab-soft-serve-known-gaps_NOTE_07-08-26.md` for what
   was carried forward.

## References

- [agent-detection-architecture.md](./agent-detection-architecture.md) — §5d has the full write-up
- [ai-behind-solution-old-vs-new.md](./ai-behind-solution-old-vs-new.md) — §4b compares `_bam` vs `_bfm`
- [deployment-guide.md](./deployment-guide.md) — Beam Lab ops section
- `process/features/evallayer/completed/agent-gate-lab_31-07-26/`
- `process/features/evallayer/completed/agent-gate-soft-serve_31-07-26/`
