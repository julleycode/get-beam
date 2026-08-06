---
name: note:ws2-emailability-tier-visibility-only
description: "User decision: WS2 agent-operated session classifier gets a visibility-only emailability tier (not hard-exclude), matching the is_bot_suspect / is_internal_suspect precedent — is_emailable_identity() stays at 3 params. Must be transcribed into the WS2 SPEC by whoever owns process/features/pixel/active/ws2-agent-session-activation_07-08-26/."
date: 07-08-26
feature: pixel
---

# WS2 agent-operated emailability tier — visibility-only (user decision)

**TL;DR** — The user decided that when the WS2 agent-operated session classifier (in
`process/features/pixel/active/ws2-agent-session-activation_07-08-26/`) flags a session as
agent-operated, that flag stays **visibility-only** — it does NOT hard-exclude the identity from
`is_emailable_identity()`. This mirrors the existing `is_bot_suspect` / `is_internal_suspect`
precedent (flag-and-surface, not flag-and-block) and keeps `is_emailable_identity()` at its
current 3-parameter signature (the same signature `tests/unit/test_cadence_bot_flag.py:293`
already asserts).

## Why this note exists here and not in the WS2 SPEC directly

The natural home for this decision is the WS2 SPEC/PLAN, but
`process/features/pixel/active/ws2-agent-session-activation_07-08-26/` is under a **hard
exclusion** for this UPDATE PROCESS session — a concurrent Claude session is actively running a
PVL loop in that folder and must not be touched. This note exists so the decision is not lost;
it must be transcribed into the WS2 SPEC by whoever owns that folder next.

## The decision, precisely

- New flag (name TBD by WS2's own design — not decided here): visibility-only, same pattern as
  `is_bot_suspect` / `is_internal_suspect`.
- `is_emailable_identity()` (`apps/api/services/identity_classification.py`) is **NOT** modified
  to add a 4th parameter or a new hard-exclude branch for this flag. It stays at 3 params.
- The flag is surfaced (dashboard, filters, analytics) but does not itself un-email a contact.
- This is consistent with the existing repo precedent: bot-suspicion and internal-traffic
  suspicion are both flag-and-surface signals, not flag-and-block signals, at the identity layer.

## What this does NOT decide

- The exact flag name, storage location, or classifier internals — those are WS2's own design
  surface, unaffected by this note.
- Whether some OTHER future signal should hard-exclude — this note is scoped to the WS2
  agent-operated classifier only.

## Action required

Whoever next works `process/features/pixel/active/ws2-agent-session-activation_07-08-26/` must
transcribe this decision into that folder's SPEC (and PLAN, if the PLAN currently leaves this
open) before treating the emailability-tier question as settled. Do not silently assume
hard-exclude was chosen — it explicitly was not.
