---
name: plan:graph-erasure-migration-live-roundtrip
description: "Backlog: the erasure_requests migration d1a6c4e93f27 is offline-validated only — no live round-trip on a disposable Postgres (KG-5)"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# erasure_requests Migration — Live Round-Trip Not Run (KG-5)

**Source:** `graph-erasure-compliance_07-08-26`, Known Gap KG-5.

## Gap

Migration `d1a6c4e93f27_add_erasure_requests.py` (chained on `c9f4a7b31e85`, the live single head
re-derived at EXECUTE time) creates the `erasure_requests` table plus two indexes. It has **not**
been round-tripped (`upgrade head` → `downgrade -1` → `upgrade head`) against a real Postgres,
because the Docker daemon was down in the EXECUTE environment.

It joins the queue of migrations already pending live-apply. Do not claim schema verification beyond
offline validation.

## Reproduce the gate

```
docker compose -f infra/docker-compose.yml up -d postgres
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads     # re-derive; never hardcode
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini downgrade -1
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head
```

## Gotcha

Offline `--sql` validation of this chain needs an EXPLICIT `<from>:<to>` range. The
`upgrade head --sql` shorthand fails mid-chain because `b7d3e9f1a4c2_add_ad_connections.py` calls
`sa.inspect(bind)`, which is unsupported against alembic's offline `MockConnection`.

## Deploy note

Railway runs `alembic upgrade head` on every boot, so pushing to `main` applies this in production.
Re-run `heads` immediately before any live apply — concurrent programs repeatedly advance it.
