# campaigns-outreach

<!-- Part of Beam -->

## Scope

Everything from enriched visitors to outreach: AI segmentation (10+ enriched visitors trigger), AI campaign planning (multi-touchpoint plans with ready-to-send copy), email sending (SendGrid/Gmail, 50/hr cap, human approval gate), social reply/DM drafts (EasyEngage voice-matched), suppression/opt-out, and conversion attribution. The agentic-lite AI layer lives here.

## Key Source Files

- `apps/api/agents/segmenter.py` — visitor batch → 2-5 segments (Gemini JSON + repair)
- `apps/api/agents/campaign_planner.py` — segment → campaign plan (JSON repair; opt-in tool loop behind `CAMPAIGN_PLANNER_TOOLS_ENABLED`)
- `apps/api/agents/workspace_tools.py` — read-only ToolSpec registries (`build_ask_tools`, `build_planner_tools`)
- `apps/api/agents/prompt_safety.py` — MANDATORY sanitize/fence for visitor data in prompts
- `apps/api/services/gemini_client.py` — `gemini_generate` / `gemini_generate_json` / `gemini_agent_loop`
- `apps/api/routers/campaigns.py`, `apps/api/routers/ai.py` (`/ai/ask` agentic assistant), `apps/api/routers/drafts*.py`
- `apps/api/services/email_sender*.py`, `apps/api/services/ai_reply.py`, `apps/api/services/suppression*.py`
- `apps/api/tasks/segmentation_tasks.py` — hourly trigger → segment → plan loop
- `apps/api/models/segment.py`, `apps/api/models/campaign.py`, `apps/api/models/draft.py`

## Related Context

- `process/context/all-context.md` — AI Layer section + Business Guardrails #1 (never auto-send)
- `process/context/tests/all-tests.md` — Gemini patch seams for tests

## Current Status

Status: stable — agentic-lite upgrade shipped 20-07-26 (JSON self-correction live; `/ai/ask` tool loop live with fallback; planner tool loop gated OFF pending live-model validation).

**Active:** `linkedin-extension_25-07-26` — Chrome/Edge MV3 browser extension (`apps/extension/`)
replacing manual DevTools `li_at` cookie-copy with one-click LinkedIn outreach connect; "dumb pipe"
to the dashboard tab, zero backend change. CODE DONE 25-07-26 (all gates re-confirmed green except
3 dev-stack-gated web-e2e cases + Postgres-gated regression — see task folder REPORT + backlog
note). Kept in `active/` pending human VERIFIED sign-off against a real LinkedIn session — see
`process/features/campaigns-outreach/active/linkedin-extension_25-07-26/`.

## Folder Contents

```
process/features/campaigns-outreach/
  active/       -- in-progress plans (each task in a {slug}_{date}/ folder)
  completed/    -- archived completed plans
  backlog/      -- deferred/future plans
```

All artifacts colocate inside each `{slug}_{date}/` task folder. Do NOT create `reports/` or `references/` sibling dirs.
