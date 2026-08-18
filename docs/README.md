# Beam Documentation

Last updated: 2026-08-18

Human-facing documentation for the Beam monorepo. Agent harness context lives separately in `process/context/` (see [all-context.md](../process/context/all-context.md)).

## Contents

| Doc | Description |
|-----|-------------|
| [identity-us-current-handoff.md](./identity-us-current-handoff.md) | Current visitor-identity handoff; read first for live status |
| [visitor-identity-flow-architecture.md](./visitor-identity-flow-architecture.md) | Luồng định danh visitor: input fields gửi cho từng provider, waterfall pre/paid, match logic Leadpipe/Capturify, so sánh `main-backup1_8`, đề xuất tối ưu input |
| [project-overview-pdr.md](./project-overview-pdr.md) | Product overview, users, constraints, PDR |
| [codebase-summary.md](./codebase-summary.md) | Repository map, LOC orientation, drift notes |
| [code-standards.md](./code-standards.md) | Structure, naming, patterns observed in code |
| [system-architecture.md](./system-architecture.md) | Components, data flows, diagrams |
| [agent-detection-architecture.md](./agent-detection-architecture.md) | AI-agent layer: 5 detection layers, confidence tiers, handoff correlation, agent-facing gateway, Beam Lab soft-serve gate + edge `_bfm` marker (§5d) — plus what it cannot do yet. Read before touching Agents/Visitors |
| [ai-behind-solution-old-vs-new.md](./ai-behind-solution-old-vs-new.md) | Giải pháp “người đứng sau AI”: SA 3 tầng, cách cũ (temporal) vs cách mới (marker F2 `_bam`), edge marker `_bfm` (§4b), phần identity còn thiếu |
| [leadpipe-webhook-team-brief.md](./leadpipe-webhook-team-brief.md) | **Trình bày team** — Leadpipe tự báo danh tính thay vì Beam đi hỏi: trước/sau, ảnh hưởng, việc phải làm tay, ít thuật ngữ |
| [beam-lab-team-brief.md](./beam-lab-team-brief.md) | **Trình bày team** — quá trình / được / hỏng, sơ đồ luồng, ít thuật ngữ |
| [beam-lab-resume.md](./beam-lab-resume.md) | Evergreen handoff kỹ thuật Beam Lab: file khoá, `_bam` vs `_bfm`, env, việc còn mở |
| [project-roadmap.md](./project-roadmap.md) | Shipped vs pending (roadmap + `process/features/`) |
| [deployment-guide.md](./deployment-guide.md) | Local, Docker, **GetBeam PROD** (Vercel + Railway + Supabase), pixel CDN, lab vs prod beacons, **scale-ready operator runbook** |
| [local-uat-prod.md](./local-uat-prod.md) | Local → UAT → PROD environments |
| [journals/](./journals/) | Session journals — latest: [260818 scale-ready cook P1–P3](./journals/260818-1328-scale-ready-getbeam-cook.md) |
| [dev-workflow-slack-issues.md](./dev-workflow-slack-issues.md) | `dev_*` branches, Slack UAT notify (proposed), GitHub Issues |
| [design-guidelines.md](./design-guidelines.md) | Web UI tokens, fonts, shadcn/Tailwind |
| [visuals/](./visuals/) | Tech-graph SVG/PNG (architecture, env promotion) |

## Quick Start

1. Windows: `.\scripts\dev-local.ps1` — macOS: `./scripts/dev-local.sh` (Windows: use Postgres port **5433**, not 5432 — see [deployment-guide.md](./deployment-guide.md#windows-local-verified))
2. Read [local-uat-prod.md](./local-uat-prod.md) for Local → UAT → PROD.
3. For current visitor-identity status and next steps, read [identity-us-current-handoff.md](./identity-us-current-handoff.md) first.
4. Read [dev-workflow-slack-issues.md](./dev-workflow-slack-issues.md) for branch naming, Issues, and Slack UAT design.
5. Read [deployment-guide.md](./deployment-guide.md) for manual commands.
6. Read [system-architecture.md](./system-architecture.md) for how apps connect.
7. For tests: [TESTING.md](../TESTING.md) and `process/context/tests/all-tests.md`.
8. Knowledge graph: open `apps/graphify-out/graph.html` (regenerate: `graphify update apps`).

## References

- Root [README.md](../README.md) — quick start commands
- [PRODUCT_ROADMAP.md](../PRODUCT_ROADMAP.md) — historical MVP spec (partially stale)
- `process/features/*/_GUIDE.md` — feature-scoped scopes and active plans
