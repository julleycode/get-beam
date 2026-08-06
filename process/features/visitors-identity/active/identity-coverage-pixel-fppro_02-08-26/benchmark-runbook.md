---
name: report:fppro-benchmark-runbook
description: "US ground-truth benchmark runbook — how to recruit 30-50 US residential testers, run the panel, and compute Coverage/Precision/FPR to decide Fingerprint Pro buy/no-buy and Leadpipe keep/kill"
date: 07-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: "4"
---

# US ground-truth benchmark runbook

**TL;DR** — This is the measuring instrument, not the measurement. Recruit 30-50 US residential
testers, have each run 2 visits (normal + incognito), record one CSV row per visit, then compute
Coverage / Precision / FPR. Two decisions ride on the output: (a) buy or skip Fingerprint Pro
(Phase 3), (b) keep or kill Leadpipe (recovery program). Nothing here runs automatically — the
panel is a human, live-provider activity and is deliberately out of scope for any agent.

Companion file: `benchmark-template.csv` (same folder). Fake rows only.

---

## 1. What this measures

Three separate things, deliberately not averaged together:

| Arm | Question | Columns that answer it |
|---|---|---|
| **Person coverage** (vendor pixel) | Does the vendor return a name/email at all, and is it the right person? | `provider_returned_match`, `provider_name`, `provider_email`, `truth_*`, `verdict` |
| **Device continuity — Fingerprint Pro** | Does one `visitorId` survive incognito and time? | `fppro_visitor_id`, `fppro_same_visitorid_across_incognito` |
| **Device continuity — Beam fp3 (comparison arm)** | Does Beam's own fonts+audio hash already survive the same conditions? | `beam_fp3`, `beam_fp3_stable_vs_prev_visit` |

The third arm exists because Beam's own fp3 (installed-font probe + audio-stack probe, shipped
07-08-26) may already close the Safari/ITP continuity gap that Fingerprint Pro is being considered
for. **If fp3 holds as well as Pro on the same testers, Pro is not worth buying.** Run both arms on
every single visit — never one without the other, or the comparison is worthless.

---

## 2. Recruitment criteria

Target: **30-50 testers.** Hard floor N ≥ 30 before any product decision (below that the numbers
are noise, per the phase risk note).

Required of every tester:

- **US resident**, on a **US residential ISP** (Comcast, Spectrum, AT&T, Verizon Fios, Cox, T-Mobile
  Home, or a US mobile carrier). Person-graph vendors have effectively no non-US coverage — a
  non-US tester tells you nothing about the vendor.
- **No VPN, no corporate proxy, no Apple Private Relay** during the run (see §5 rule R4 for why).
  Ask them to check: Safari → Settings → iCloud → Private Relay must be **off**; no VPN app
  connected.
- Willing to give their **real name and real email as ground truth** — this is the whole point, and
  it is also why the filled sheet is never committed (see §7).
- Reachable for a **follow-up visit at least 24 hours later** (the time-decay leg).

Aim for spread, not a monoculture:

- **Browser mix:** at least 8 Safari (this is where ITP bites hardest), at least 8 Chrome, some
  Firefox and Edge.
- **Device mix:** at least 10 mobile (iOS + Android), rest desktop.
- **Geography:** at least 5 distinct states.

Recruit from: existing Beam users who opt in, personal network, a paid panel provider, or a
small-scale task marketplace. Do not recruit from a single Slack/Discord — you will get one
browser and one region.

---

## 3. Tester procedure (give them this verbatim)

Each tester produces **2 rows minimum** (visit 1 and visit 2). A third row is optional.

**Visit 1 — normal window, day 1**

1. Turn VPN and Apple Private Relay **off**. Confirm.
2. Open the Lab site URL in your **normal** browser window (not incognito).
3. Load the page, scroll to the bottom, wait ~15 seconds. Do not fill in any form.
4. Tell the operator you are done, and send your **name + email** (this is the ground truth).

**Visit 2 — incognito / private window, same day**

5. Open a **new incognito / private window** (Chrome: Incognito; Safari: Private; Firefox: Private).
6. Load the same Lab site URL. Scroll, wait ~15 seconds. Again, no form.
7. Tell the operator you are done.

**Visit 3 — optional, ≥ 24 hours later**

8. Repeat Visit 1 in a normal window at least 24 hours after Visit 1. This is the time-decay leg
   for both continuity arms.

Testers do not need to see or record any IDs. The operator pulls all technical fields from the Lab
DB / Fingerprint dashboard afterwards and pairs them by timestamp + tester id.

---

## 4. Operator procedure (per visit)

1. Assign a stable `tester_id` (`T001`, `T002`, …) — reuse the same id across that tester's visits.
2. Pull from the Lab DB for that visit: `beam_visitor_id`, `beam_fp2`, `beam_fp3`.
3. Pull from the Fingerprint dashboard (Phase 3 arm only): `fppro_visitor_id`, VPN signal, bot
   signal.
4. Pull vendor output: did the provider return a match, and what name/email.
5. Fill `truth_name` / `truth_email` from what the tester sent.
6. Set the derived columns per §5.
7. Append one row. One row = one visit. Never merge two visits into one row.

**Derived-column rules:**

- `beam_fp3_stable_vs_prev_visit` — `y` if `beam_fp3` equals this tester's previous visit's value,
  `n` if different, `n/a` on visit 1.
- `fppro_same_visitorid_across_incognito` — `y` if the incognito visit's `fppro_visitor_id` equals
  the normal visit's, `n` if different, `n/a` on visit 1. This is the column the phase's success
  criteria specifically require.
- `name_match` — `y` only if `provider_name` is the same human as `truth_name` (ignore casing,
  middle names, and nicknames; "Jon" vs "Jonathan" is a match, "Jon Smith" vs "Jane Smith" is not).
- `email_match` — `y` only on an **exact** normalized match (lowercase, trim). Nothing fuzzy —
  a near-miss email is a wrong email, because Beam would send to it.
- `verdict` — exactly one of:
  - `no_match` — provider returned nothing.
  - `correct` — provider returned a match AND `email_match = y`.
  - `wrong` — provider returned a match AND `email_match = n`. This is a false positive.
- `exclude_from_metrics` + `exclusion_reason` — see rule R4 below.

---

## 5. Metric definitions (exact formulas)

Let, over the **eligible row set** (see R1-R4):

- `T` = total eligible visits
- `M` = eligible visits where `provider_returned_match = y`
- `C` = eligible visits where `verdict = correct`
- `W` = eligible visits where `verdict = wrong`

Then:

```
Coverage  = M / T          # how often the vendor says anything at all
Precision = C / M          # of the times it spoke, how often it was right
FPR       = W / M          # of the times it spoke, how often it was wrong
```

Note `Precision + FPR = 1` by construction (`M = C + W`), so FPR is reported for readability, not
as independent information. If they do not sum to 1, a row has a bad `verdict` — fix the row.

Continuity arms are counted separately, as simple rates over paired visits:

```
FpPro continuity = (# visits where fppro_same_visitorid_across_incognito = y)
                   / (# visits where that column is y or n)

Beam fp3 continuity = (# visits where beam_fp3_stable_vs_prev_visit = y)
                      / (# visits where that column is y or n)
```

Report both **overall** and **split by browser family** (Safari vs Chromium vs Firefox). The Safari
split is the whole reason continuity is being measured — an overall number that hides a Safari
collapse is a misleading number.

### Eligibility rules

- **R1 — N ≥ 30 distinct testers.** Below that, publish nothing and make no decision.
- **R2 — Denominator is visits, not testers.** A tester with 3 visits contributes 3 rows.
- **R3 — Ground truth required.** A row with empty `truth_email` is excluded (you cannot score it).
- **R4 — VPN / Private Relay / corporate-proxy rows are excluded from Coverage, Precision, and
  FPR.** Set `exclude_from_metrics = y` with the reason. The person-graph cell is invalid on those
  networks — including them fabricates a low Coverage that says nothing about the vendor. Keep the
  rows in the file anyway: they are the only data that scores `fppro_vpn_signal` accuracy.
- **R5 — Bot-flagged rows excluded** (`fppro_bot_signal = true`), same treatment as R4.

---

## 6. Pass bar and decisions

### Pass bar — vendor pixel path

Per the phase file's stated example bar:

| Metric | Bar | Meaning if missed |
|---|---|---|
| **Precision** | **≥ 0.70** | Do not enable the pixel path on more sites. Under 0.7, ~1 in 3 candidates is the wrong human. |
| **Coverage** | report only, no bar | Low coverage is a value question, not a safety question. |
| **N** | **≥ 30 testers** | No decision at all. |

Precision is the gate because a wrong candidate is an outreach-safety problem; low coverage is
merely disappointing. Note that `provider_candidate` is never emailable regardless — the bar
governs whether the path is worth expanding, not whether it is safe to send from.

### Pass bar — continuity arms

| Comparison | Decision |
|---|---|
| `FpPro continuity - Beam fp3 continuity` **< 0.10** on Safari | **No-buy.** Beam's own fp3 already covers the gap; paying per-identification for a ≤10pt delta is not justified. |
| Delta **≥ 0.10** on Safari, and fp3 Safari continuity is itself weak (< 0.60) | **Buy candidate.** Proceed with Phase 3 behind its default-off flag, and budget-gate the per-call cost. |
| Both arms weak (< 0.50 Safari) | Neither solves it. Do not buy; log as an open architectural gap. |

### Decision A — Fingerprint Pro buy / no-buy (Phase 3)

Owner input: the two continuity rates split by browser, plus per-identification cost. Phase 3
stays `pending` until this decision is recorded. **Explicitly record the Beam-fp3 comparison arm in
the decision** — the buy case only exists if fp3 measurably fails where Pro holds.

### Decision B — Leadpipe keep / kill (recovery program)

Owner input: Coverage and Precision on the vendor arm. Note this benchmark cannot run at all until
the recovery program clears the live blocker (Leadpipe account expired, `pixels_active=0`,
`/v1/data` → 403). A benchmark run against a dead account measures nothing. Sequence:
recovery unblocks the vendor → panel runs → Decision B.

After the first 30 testers, write a REPORT into this same task folder with the numbers and both
decisions.

---

## 7. PII rules (non-negotiable)

- **`benchmark-template.csv` in git contains fake rows only.** Every example value uses
  `example.invalid` addresses and obviously-fake names. Do not "improve" it with real data.
- **The filled sheet is never committed.** Keep it outside the repo (local disk or a private sheet).
  If a filled copy must live near the repo, add it to `.gitignore` first and verify with
  `git check-ignore`.
- Real `truth_email` values are the highest-sensitivity field in this whole exercise — a tester
  handed them over for one measurement, not for a repository.
- Any derived report committed to the repo carries **aggregate numbers only** — no names, no
  emails, no per-tester rows.
- Testers should be told, in one line, what the data is for and that it is deleted after the
  benchmark. Delete the filled sheet once the REPORT is written.

---

## 8. Not in scope here

- Running the panel (human + live-provider activity — needs explicit operator action).
- Any Lab DB export helper script. Dropped as YAGNI: with no panel recruited, an exporter has
  nothing to export and would be built against guessed column needs. Revisit only if a panel is
  actually assembled and manual pulls prove painful.
- Any source-code change. This phase is docs-only.
