# Supabase — project pin + DB IDE connect

Last updated: 2026-08-09

## Canonical project (pinned)

This Beam repo uses **one** Supabase project for production Postgres:

| Field | Value |
|---|---|
| **Project name** | `retarget-agent` |
| **Project ref / id** | `hylcleqxlkdblibpdhhm` |
| Region | `ap-southeast-1` |
| Status (checked 09-08-26) | `ACTIVE_HEALTHY` |
| API URL | `https://hylcleqxlkdblibpdhhm.supabase.co` |
| Direct DB host | `db.hylcleqxlkdblibpdhhm.supabase.co` |
| Dashboard | https://supabase.com/dashboard/project/hylcleqxlkdblibpdhhm |
| Connect dialog | https://supabase.com/dashboard/project/hylcleqxlkdblibpdhhm?showConnect=true |

**Rule for agents / MCP:** when calling Supabase MCP (`list_tables`, `execute_sql`, `get_logs`, migrations, etc.), always pass `project_id` / `id` = **`hylcleqxlkdblibpdhhm`** (`retarget-agent`).

Do **not** use:

- `buildtolaunch` (`lnhymfqslmbdpklkpqwp`)
- `supabase-fuchsia-book` (`kqvkqgwzbpoailbigxbt`, often INACTIVE)

Also see the safety note in `process/context/all-context.md`: bare `alembic upgrade` with repo `.env` can hit this prod DSN — pin local Docker (`localhost:5433`) for non-prod work.

---

## Connect a local DB IDE (DBeaver / DataGrip / TablePlus / pgAdmin / VS Code)

You connect over **PostgreSQL**. Password is **not** stored in this repo — copy it from the Supabase dashboard (or reset under Database Settings).

### 1. Copy credentials from Supabase

1. Open [Connect](https://supabase.com/dashboard/project/hylcleqxlkdblibpdhhm?showConnect=true).
2. Prefer **Session pooler** for IDE clients on typical Windows/IPv4 networks (port **5432**).
3. Note: host, port, database (`postgres`), user, password.
4. Optional: download the SSL CA from [Database Settings](https://supabase.com/dashboard/project/hylcleqxlkdblibpdhhm/database/settings).

Official guide (DBeaver): https://supabase.com/docs/guides/database/dbeaver

### 2. Which connection mode?

| Mode | Typical host | Port | Best for |
|---|---|---|---|
| **Session pooler** (recommended for IDE) | `aws-*-ap-southeast-1.pooler.supabase.com` (exact host from Connect UI) | `5432` | DBeaver / DataGrip / TablePlus on IPv4 |
| Direct | `db.hylcleqxlkdblibpdhhm.supabase.co` | `5432` | Migrations / `pg_dump`; often IPv6-only without add-on |
| Transaction pooler | same pooler host family | `6543` | Serverless/app traffic — **not** ideal for interactive IDE |

Pooler usernames look like `postgres.hylcleqxlkdblibpdhhm` (not bare `postgres`). Always paste the username from the Connect dialog.

### 3. Fill the IDE (PostgreSQL)

| Field | Value |
|---|---|
| Host | from Connect (session pooler host) |
| Port | `5432` (session) |
| Database | `postgres` |
| User | from Connect (often `postgres.hylcleqxlkdblibpdhhm`) |
| Password | database password from dashboard |
| SSL | required — enable SSL; attach CA if the client asks |

**DBeaver:** New Connection → PostgreSQL → Main tab (host/user/password) → SSL tab (use CA / require) → Test Connection.

**DataGrip / TablePlus / pgAdmin:** same fields; driver = PostgreSQL; SSL on.

**VS Code:** extension such as “PostgreSQL” / “SQLTools” + PostgreSQL driver; paste URI from Connect or fill host/port/user/db.

Example URI shape (password redacted — do not commit real URIs):

```text
postgresql://postgres.hylcleqxlkdblibpdhhm:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
```

(Exact pooler hostname may differ — always copy from the Connect UI.)

### 4. Where to get the database password

Supabase **never shows** the existing DB password again (Connect UI only prints `[YOUR-PASSWORD]`).

| Source | Notes |
|---|---|
| Railway `DATABASE_URL` (service API / `retarget-agent`) | Password is the segment between `:` and `@` in the URI |
| Reset in dashboard | Connect → **Reset database password**, then update Railway + every other consumer |
| Repo `.env` | Usually points at **local Docker** (`localhost:5433`) — not prod |

**Never commit passwords or full prod DSNs into docs/git.**

In a URI like:

```text
postgresql+asyncpg://USER:PASSWORD@HOST:5432/postgres
```

`PASSWORD` is only the part between the first `:` after `USER` and the `@`.

### 5. Safety while browsing prod

- Treat this as **production**. Prefer read-only queries in the IDE.
- Do not run destructive SQL or `alembic upgrade` against this DSN from a laptop unless you intentionally mean prod.
- Local app/dev DB remains Docker on **`localhost:5433`** (see `.env.example` and `docs/deployment-guide.md`).
- Prefer **Session pooler** (`aws-1-ap-southeast-1.pooler.supabase.com:5432`, user `postgres.hylcleqxlkdblibpdhhm`) on IPv4 networks. Direct host `db.hylcleqxlkdblibpdhhm.supabase.co` is IPv6-default and often fails from Windows without the IPv4 add-on.
- IDE driver = **PostgreSQL** (not a separate “Supabase” engine). Use `sslmode=require`.

---

## Sync `ip_org_prefixes` PROD → local Docker

Pinned 09-08-26. Local Docker: `localhost:5433`, db `retarget_agent`, user `retarget` (see `.env.example`).

Prod table (checked via MCP): ~969k rows / ~255 MB, columns include Phase-3 fields
`relationship_type`, `valid_from`, `valid_to`, `as2org_org_id`.

### Recipe (`pg_dump` / `pg_restore`)

Password from Railway / operator vault only — inject via env, do not paste into the repo:

```powershell
# PROD (Session pooler) — set PGPASSWORD from Railway, never commit it
$env:PGPASSWORD = '<from-Railway-DATABASE_URL>'
$env:PGSSLMODE = 'require'
$dump = Join-Path $env:TEMP 'ip_org_prefixes.dump'

pg_dump `
  -h aws-1-ap-southeast-1.pooler.supabase.com -p 5432 `
  -U postgres.hylcleqxlkdblibpdhhm -d postgres `
  -t ip_org_prefixes --no-owner --no-acl -F c -f $dump

# LOCAL Docker (drops/recreates table to match PROD schema)
$env:PGPASSWORD = 'retarget_dev'
$env:PGSSLMODE = 'disable'
psql -h localhost -p 5433 -U retarget -d retarget_agent `
  -c "DROP TABLE IF EXISTS ip_org_prefixes CASCADE;"

pg_restore -h localhost -p 5433 -U retarget -d retarget_agent `
  --no-owner --no-acl -t ip_org_prefixes $dump

psql -h localhost -p 5433 -U retarget -d retarget_agent `
  -c "SELECT count(*) FROM ip_org_prefixes;"
```

Expect local `count(*)` ≈ prod (~969076). Delete the dump file from `%TEMP%` after verify.

If local already had an older `ip_org_prefixes` (pre Phase-3 columns), **DROP + restore** is required — data-only copy into the old schema will fail.

**PG17 (Supabase) → PG16 (local Docker) caveat:** `pg_restore` may warn
`unrecognized configuration parameter "transaction_timeout"` and exit `1` while still
loading rows. If indexes/`PRIMARY KEY` are missing afterward, recreate:

```sql
ALTER TABLE ip_org_prefixes ADD CONSTRAINT ip_org_prefixes_pkey PRIMARY KEY (id);
CREATE INDEX idx_ip_org_prefixes_prefix_gist ON public.ip_org_prefixes USING gist (prefix inet_ops);
CREATE INDEX idx_ip_org_prefixes_asn ON public.ip_org_prefixes USING btree (asn);
CREATE INDEX idx_ip_org_prefixes_org_name ON public.ip_org_prefixes USING btree (org_name);
CREATE INDEX idx_ip_org_prefixes_relationship_type ON public.ip_org_prefixes USING btree (relationship_type);
ANALYZE ip_org_prefixes;
```

**Verified 09-08-26 on this machine:** local `count(*)=969076`, 15 columns (incl. Phase-3), 5 indexes, ~246 MB.

Also created empty local mirrors (09-08-26): `rpki_roas` (GiST `inet_ops`) and `events_fallback`
(PROD-only orphan — not owned by an alembic revision in-repo). Local `alembic_version` stamped
to **`d3f9a1c25e84`** after pulling migrations `c4a8f13e07b6` + `d3f9a1c25e84` from `main` onto
`dev_nhantc2`. Do **not** re-run those upgrades against a DB that already has the Phase-3 columns
from a PROD dump — use `alembic stamp` instead.

---

## MCP quick reference

```text
project_id / id = hylcleqxlkdblibpdhhm
name          = retarget-agent
```
