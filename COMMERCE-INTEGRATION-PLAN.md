# Agentic commerce coordination plan

This file routes the individual guides; their plans own technical assessment and
implementation. Coordinator guide: https://directory.inflowpay.ai/integration.md
(template: https://directory.inflowpay.ai/integration-queue-template.md).
Do not record secrets, personal data, or duplicate child queues here.

## Scope and route

- Target repository and application: `github.com/julleycode/get-beam` (local clone
  `~/get-beam`, branch `feat/agentic-commerce` off `main`). Monorepo with
  `apps/api`, `apps/web`, `apps/extension`, `apps/pixel`. Target application not
  yet identified by developer ("not sure"); the Payments child guide determines
  it from current source and confirms with the developer.
- Selected capabilities: Payments (InFlow), AEP, ODP (all three).
- Excluded capabilities: none.
- Approved order: Payments → AEP → ODP (confirmed by developer "go", 30-09-26).
- Process note: developer instructed to skip the repo's RIPER-5 harness; guides' own stages govern.
- Existing answers to pass to the individual guides:
  - Payments: role Both; protocols MPP + x402; first integration; Sandbox first.
  - All three capabilities selected.
  - Work on branch `feat/agentic-commerce`; no commits/PRs without explicit approval.
  - Service = `apps/api` (fulfillment) + `apps/web` (agent-facing paid route handlers).
  - Developer instructed to skip the repo's RIPER-5 harness; other repo instructions still apply.
- Approval or scope decisions still needed:
  - Payments plan approval (see child plan Active work).

## Individual integrations

| Order | Integration     | Guide URL                                       | Child-plan path              | Stage       | State                 | Next action                      |
| ----- | --------------- | ----------------------------------------------- | ---------------------------- | ----------- | --------------------- | -------------------------------- |
| 10    | InFlow Payments | https://app.inflowpay.ai/integration.md         | `INFLOW-INTEGRATION-PLAN.md` | Verification | Seller DONE (Sandbox-verified, prod dormant); Buyer PAUSED | Buyer resumes when InFlow auto-approval + prod access exist |
| 20    | AEP             | https://www.aep.foundation/integration.md       | `AEP-INTEGRATION-PLAN.md`    | Plan awaiting approval | Waiting for developer | Approve AEP plan → task 10 spike |
| 30    | ODP             | https://www.offeringprotocol.org/integration.md | `ODP-INTEGRATION-PLAN.md`    | Not started | Queued                | Begin after AEP handoff          |

## Current handoff

- Active guide and stage: AEP guide, stage 5 — plan awaiting approval (01-10-26).
- Last completed step and evidence: Payments handoff — Seller: 4 routes × MPP/x402 settled in Sandbox, no-match not charged, replay rejected; deployed dormant (Railway d947910e, Vercel; /api/paid 404). Buyer: built + unit-verified, Sandbox self-test blocked by InFlow approval requirement (X402ApprovalTimeoutError, no charge); paused by developer. Unpushed commits after 61d6008: 564eaee, 9f86dd4, 88a0a4b, 7bddeae (+ plan updates).
- Confirmed decisions: all three; order Payments → AEP → ODP; branch `feat/agentic-commerce`; skip RIPER-5; Payments Seller = 4 paid `/api/paid/*` endpoints in `apps/web` (Next.js route handlers) calling Python internal endpoints; Buyer = Locus Apollo reseller fallback, flag OFF, capped; stage 4 defaults accepted.
- Pending question or blocker: AEP interview answers. Payments open items: Buyer approval policy (ask InFlow), production InFlow login, unexplained −2.00 USDC Sandbox balance, push of unpushed commits.
- Destination guide, if switching: none.
- What the child must reassess on resumption: re-verify code state against assessment before task 10.
- Precise next action: developer approves `AEP-INTEGRATION-PLAN.md` → task 10 spike.
- Authorization needed: Node 22 pin.

## Remaining coordination work

| Work                                                        | Responsible child | Dependency or decision               | State   |
| ----------------------------------------------------------- | ----------------- | ------------------------------------ | ------- |
| Discovery → enrollment → paid Action end-to-end verification | ODP child plan    | Payments and AEP implemented; authorization and spending limits | Pending |
| Tenant-bound ops (visitor identify, segments, campaign plan) via AEP-authenticated agent access | AEP child plan | Excluded from Payments scope | Pending |
| Advertise 4 paid Actions (`/api/paid/*`), prices, MPP + x402 options | ODP child plan | Payments task 40 done | Pending |
| Existing agent gateway (`routers/agent_gateway.py`, `agent_mcp.py`) overlaps ODP/AEP surfaces | ODP / AEP child plans | — | Pending |

## Exit criteria and evidence

### Project acceptance

| Child plan                   | Required project checks                              | Result  | Evidence or blocker |
| ---------------------------- | ---------------------------------------------------- | ------- | ------------------- |
| `INFLOW-INTEGRATION-PLAN.md` | pytest unit + integration, web lint / vitest / build / e2e, diff review | Pending | Plan written |
| `AEP-INTEGRATION-PLAN.md`    | Determined by AEP child from project                 | Pending | Not started         |
| `ODP-INTEGRATION-PLAN.md`    | Determined by ODP child from project                 | Pending | Not started         |

### InFlow acceptance

| Child plan                   | Running-system criterion                              | Environment and target | Result  | Evidence or blocker |
| ---------------------------- | ----------------------------------------------------- | ---------------------- | ------- | ------------------- |
| `INFLOW-INTEGRATION-PLAN.md` | `inflow mpp pay` + `inflow x402 pay` per paid route; Buyer reference + app check | Sandbox local via tunnel; Buyer production | Seller: PASS local Sandbox (01-10-26); Buyer + deployed: Pending | Child plan § InFlow acceptance |
| `AEP-INTEGRATION-PLAN.md`    | `inflow aep enroll`                                   | TBD                    | Pending | Not started         |
| `ODP-INTEGRATION-PLAN.md`    | `inflow odp inspect` + Directory publication          | TBD                    | Pending | Not started         |

## Final handoff

- Completed capabilities and child-plan links: none yet.
- Project acceptance results: pending.
- InFlow acceptance results: pending.
- Pending or explicitly deferred criteria and their owners: all.
- Precise next action: see Current handoff.
