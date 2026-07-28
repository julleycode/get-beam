# Beam Documentation

Last updated: 2026-07-28

Human-facing documentation for the Beam monorepo. Agent harness context lives separately in `process/context/` (see [all-context.md](../process/context/all-context.md)).

## Contents

| Doc | Description |
|-----|-------------|
| [project-overview-pdr.md](./project-overview-pdr.md) | Product overview, users, constraints, PDR |
| [codebase-summary.md](./codebase-summary.md) | Repository map, LOC orientation, drift notes |
| [code-standards.md](./code-standards.md) | Structure, naming, patterns observed in code |
| [system-architecture.md](./system-architecture.md) | Components, data flows, diagrams |
| [agent-detection-architecture.md](./agent-detection-architecture.md) | AI-agent layer: 5 detection layers, confidence tiers, handoff correlation, agent-facing gateway — plus what it cannot do yet. Read before touching Agents/Visitors |
| [project-roadmap.md](./project-roadmap.md) | Shipped vs pending (roadmap + `process/features/`) |
| [deployment-guide.md](./deployment-guide.md) | Local dev, Docker, Railway, pixel CDN; **Windows verified (port 5433)** |
| [local-uat-prod.md](./local-uat-prod.md) | Local → UAT → PROD environments |
| [dev-workflow-slack-issues.md](./dev-workflow-slack-issues.md) | `dev_*` branches, Slack UAT notify (proposed), GitHub Issues |
| [design-guidelines.md](./design-guidelines.md) | Web UI tokens, fonts, shadcn/Tailwind |
| [visuals/](./visuals/) | Tech-graph SVG/PNG (architecture, env promotion) |

## Quick Start

1. Windows: `.\scripts\dev-local.ps1` — macOS: `./scripts/dev-local.sh` (Windows: use Postgres port **5433**, not 5432 — see [deployment-guide.md](./deployment-guide.md#windows-local-verified))
2. Read [local-uat-prod.md](./local-uat-prod.md) for Local → UAT → PROD.
3. Read [dev-workflow-slack-issues.md](./dev-workflow-slack-issues.md) for branch naming, Issues, and Slack UAT design.
4. Read [deployment-guide.md](./deployment-guide.md) for manual commands.
5. Read [system-architecture.md](./system-architecture.md) for how apps connect.
6. For tests: [TESTING.md](../TESTING.md) and `process/context/tests/all-tests.md`.
7. Knowledge graph: open `apps/graphify-out/graph.html` (regenerate: `graphify update apps`).

## References

- Root [README.md](../README.md) — quick start commands
- [PRODUCT_ROADMAP.md](../PRODUCT_ROADMAP.md) — historical MVP spec (partially stale)
- `process/features/*/_GUIDE.md` — feature-scoped scopes and active plans
