---
name: note:unit-marker-coverage-gap
description: "The -m unit lane is ~34% blind: most tests/unit files carry no unit marker and nothing auto-marks by path"
date: 16-08-26
metadata:
  node_type: memory
  type: report
  feature: campaigns-outreach
  phase: phase-1
---

# The `-m unit` lane is structurally blind (cross-cutting)

**Found by:** marketing-claims-gap Phase 1 PVL (N-2), re-confirmed at EXECUTE.

`tests/conftest.py` does **not** auto-mark tests by path, and only a minority of
files under `tests/unit/` declare `pytestmark = pytest.mark.unit`. Measured
16-08-26 (a drifting snapshot — a concurrent session was adding tests):

| Lane | Collected |
|---|---|
| `pytest tests/unit -q` (UNMARKED) | ~2800 |
| `pytest tests/unit -m unit -q` | ~1840 collected, ~962 **deselected** |

So the marker lane silently skips roughly a third of the unit suite.

## Why this bites

The deselected set is not random. During Phase 1 it included:

- `tests/unit/test_link_decoration.py` — the ONLY coverage of `decorate_links`
- `tests/unit/test_personalize.py` — the ONLY coverage of `_personalize`

i.e. exactly the two modules that phase changed. A plan that adopts `-m unit` as
its regression gate is blind precisely where it is most exposed.

## Rules that follow (already applied in Phase 1)

1. **Whole-phase regression uses the UNMARKED lane:** `pytest tests/unit -q`.
2. **Every NEW test file must declare `pytestmark = pytest.mark.unit`** (or
   `integration`). An unmarked file is fully deselected by `-m unit`, and a
   fully-deselected run exits **5** — loud, not a vacuous pass.
3. Per-file gates run bare: `pytest tests/unit/<file>.py -q`.

## Candidate fix

Either backfill `pytestmark` across the unmarked files, or add a `conftest.py`
hook that auto-marks by path (`tests/unit/**` → `unit`, `tests/integration/**` →
`integration`). The hook is the smaller, drift-proof change; the backfill is
mechanical but must be re-done for every new file.

Affects **every** plan in this repo that adopts the marker lane as its
regression gate.
