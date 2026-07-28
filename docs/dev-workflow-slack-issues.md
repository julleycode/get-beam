# Dev Workflow: Branches, Slack UAT Notify, GitHub Issues

Last updated: 2026-07-28

## Overview

Professional workflow for Beam from **local development → UAT → PROD**, with:

- Feature branches named `dev_<slug>`
- Slack notifications when UAT deploys (workspace **get-beam**) — **proposed, not implemented**
- GitHub Issues as the source of truth for work tracking

Related docs:

- [local-uat-prod.md](./local-uat-prod.md) — environment topology and promotion
- [deployment-guide.md](./deployment-guide.md) — Windows local verified setup (port 5433)
- [README.md](./README.md) — documentation index

---

## Branch naming

| Branch pattern | Purpose | Deploy target |
|----------------|---------|---------------|
| `main` | Integration / release candidate | CI on every push; future UAT auto-deploy candidate |
| `UAT` | Long-lived UAT branch (exists: `origin/UAT` from `main`) | UAT environment when wired |
| `dev_<slug>` | Feature work (e.g. `dev_ads-meta`, `dev_42-onboarding`) | UAT preview when branch deploy is configured |

**Optional convention:** `dev_<issue-number>-<slug>` (e.g. `dev_42-ads-meta`) links branch to GitHub Issue at a glance.

**Status (2026-07-28):**

| Capability | Status |
|------------|--------|
| Branch `origin/UAT` | **Exists** from `main` |
| Auto-deploy `dev_*` → UAT | **Not implemented** — prerequisite: Railway/Vercel deploy-on-branch |
| Auto-deploy UAT → PROD | **Not implemented** — manual promote for now |
| Slack UAT notifications | **Not implemented** — design documented below |

---

## Slack UAT notifications (proposed)

> **Status: NOT IMPLEMENTED.** No workflow files or webhooks are committed. Implement when UAT branch deploy is wired.

### Goal

When a branch matching `dev_*` is successfully deployed to **UAT**, post a message to Slack workspace **get-beam** so the team sees what landed without digging through CI logs.

### Recommended approaches

| Option | Pros | Cons |
|--------|------|------|
| **Incoming Webhook** | Simple; one secret; easy in GitHub Actions | Channel fixed per webhook; less interactive |
| **Slack GitHub App** | Rich formatting; repo-linked | More setup in Slack app directory |
| **Slack Workflow Builder** | No code in repo | Harder to tie to deploy success |

**Recommended for Beam:** GitHub Actions → POST to Slack Incoming Webhook stored as a GitHub Actions secret.

### Trigger (when implemented)

Choose one (or both):

1. **On push** to branches matching `dev_*` after CI passes
2. **On successful deploy** to GitHub Environment `uat` (preferred — confirms deploy, not just push)

Example workflow sketch (do not add until UAT deploy exists):

```yaml
# PROPOSED — not in repo
on:
  push:
    branches: ['dev_*']
  # OR: workflow_run after deploy-uat.yml succeeds
```

### GitHub Actions secret

| Secret | Value |
|--------|-------|
| `SLACK_WEBHOOK_UAT` | Incoming Webhook URL from Slack (workspace **get-beam**) |

**Never commit the webhook URL.** Create the webhook in Slack → Apps → Incoming Webhooks; paste URL only into GitHub repo/org secrets.

### Suggested channels (workspace get-beam)

| Channel | Use |
|---------|-----|
| `#deploys-uat` | Dedicated deploy feed (recommended) |
| `#get-beam-eng` | Broader engineering channel if a separate deploy channel is not needed |

### Message fields (recommended payload)

Include in each UAT deploy notification:

| Field | Example |
|-------|---------|
| Branch | `dev_ads-meta` |
| Commit SHA | `abc1234` (short) |
| Author | `@github-user` |
| UAT API URL | `https://api.uat.getbeam.fyi` |
| UAT Web URL | `https://uat.getbeam.fyi` |
| CI / deploy link | GitHub Actions run URL |
| Related issue | `#42` (from branch name or PR body) |

Example Slack Block Kit text (illustrative):

```text
:rocket: UAT deploy — dev_ads-meta
Commit: abc1234 by @dev
API: https://api.uat.getbeam.fyi/health
Web: https://uat.getbeam.fyi
CI: <run-url>
Issue: #42
```

### Prerequisites before wiring Slack

1. UAT Railway project / Vercel preview deploys from `dev_*` or `UAT` branch
2. GitHub Environment `uat` with protection rules (optional)
3. Smoke checklist passes post-deploy (see [Definition of Done — UAT](#definition-of-done-uat))
4. Webhook secret `SLACK_WEBHOOK_UAT` in GitHub

---

## GitHub Issues management

Use **GitHub Issues** for work tracking. Use **Slack** for notifications only — not as the system of record.

### Labels

| Label | Meaning |
|-------|---------|
| `bug` | Defect |
| `feat` | New feature |
| `chore` | Maintenance, tooling, deps |
| `docs` | Documentation only |
| `uat` | Needs or blocked on UAT validation |
| `prod-blocker` | Must fix before PROD promote |
| `needs-design` | UX/spec needed before implementation |
| `P0` … `P3` | Priority (P0 = critical) |

Combine as needed: e.g. `feat`, `P1`, `uat`.

### Issue template fields (recommended)

When creating issues, include:

1. **Context** — why this work exists; link to Slack thread if relevant
2. **Acceptance criteria** — testable outcomes
3. **Environment** — `local` / `UAT` / `prod` where the bug appears or feature must be verified
4. **Branch** — suggested `dev_<slug>` or `dev_<issue#>-slug`

### Linking PRs and deploys

| Link type | Convention |
|-----------|------------|
| PR → Issue | `Fixes #N` or `Closes #N` in PR description |
| Branch → Issue | `dev_42-ads-meta` or mention `#42` in PR |
| UAT Slack message | Include `Issue: #N` when webhook is live |

### Project board states

Recommended columns (GitHub Projects or equivalent):

```text
Triage → In progress → In UAT → Ready for prod → Done
```

| State | Entry criteria |
|-------|----------------|
| **Triage** | New issue; needs priority and owner |
| **In progress** | Branch `dev_*` open; local or CI work |
| **In UAT** | Deployed to UAT; awaiting smoke / QA |
| **Ready for prod** | UAT sign-off; eligible for PROD promote |
| **Done** | Live in PROD or explicitly closed/won't fix |

### Definition of Done — UAT

An issue moves to **Ready for prod** only when UAT shows:

- [ ] Alembic migrations applied (`upgrade head` on UAT DB)
- [ ] `GET {UAT_API}/health` returns `{"status":"ok"}`
- [ ] Smoke checklist for the feature (sign-in, affected pages, pixel ingest if relevant)
- [ ] No open `prod-blocker` or `P0`/`P1` bugs for this change
- [ ] PR merged or SHA tagged for promote

Local parity checklist before opening PR: [deployment-guide.md](./deployment-guide.md#windows-local-verified).

---

## End-to-end flow (target state)

```text
Issue #42 (feat) ──► branch dev_42-ads-meta
        │
        ▼
   Local dev (dev-local.ps1 / dev-local.sh)
        │
        ▼
   PR → main (or direct merge policy TBD)
        │
        ▼
   CI green → deploy dev_* to UAT  [NOT IMPLEMENTED]
        │
        ▼
   Slack #deploys-uat notification  [NOT IMPLEMENTED]
        │
        ▼
   Issue → In UAT → smoke → Ready for prod
        │
        ▼
   Manual PROD promote (Railway / Vercel)  [current]
        │
        ▼
   Issue → Done
```

---

## Implementation checklist (for later)

Use this when automation is ready — **no action required until then.**

### Phase 1 — UAT deploy wiring

- [ ] Railway: UAT service deploys from `UAT` or `dev_*` branches
- [ ] Vercel: Preview / UAT project points at UAT API URL
- [ ] GitHub Environment `uat` with URL variables (`UAT_API_URL`, `UAT_WEB_URL`)
- [ ] Document env matrix in [local-uat-prod.md](./local-uat-prod.md)

### Phase 2 — Slack notifications

- [ ] Create Incoming Webhook in Slack workspace **get-beam**
- [ ] Add `SLACK_WEBHOOK_UAT` to GitHub Actions secrets
- [ ] Add workflow: on successful UAT deploy → POST Slack message with fields above
- [ ] Test with a throwaway `dev_test-slack` branch

### Phase 3 — Issues hygiene

- [ ] Add GitHub issue templates (bug, feat) with acceptance criteria + env fields
- [ ] Create Project board with states: Triage → … → Done
- [ ] Apply label set (`bug`, `feat`, `chore`, `docs`, `uat`, `prod-blocker`, `needs-design`, `P0`–`P3`)
- [ ] Team agreement: Issues over chat-only tracking

---

## References

- [local-uat-prod.md](./local-uat-prod.md)
- [deployment-guide.md](./deployment-guide.md)
- `.github/workflows/test.yml` — CI today (no deploy workflow yet)
- `scripts/dev-local.ps1`, `scripts/dev-local.sh`
