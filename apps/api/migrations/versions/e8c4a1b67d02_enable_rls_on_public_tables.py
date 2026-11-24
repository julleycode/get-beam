"""enable row level security on every public table

Revision ID: e8c4a1b67d02
Revises: d3f8a2c61b47
Create Date: 2026-11-24

Supabase Data API (PostgREST) exposes the public schema to the anon key.
RLS was off, so that key could read and write every row, including password
hashes, OAuth tokens, API keys, emails, and webhook secrets.

The API connects with DATABASE_URL as the table owner. On Supabase that role
bypasses RLS. Nothing in this repo queries these tables with the anon key
(the service-role key is used only for Storage uploads). No policies are
added: anon and authenticated are denied. The owner keeps full access.

Idempotent. Paste the SQL into the Supabase SQL editor, or let a later
`alembic upgrade head` run it. Do not use `supabase db push` — this repo
has no supabase/migrations directory.

"""
from alembic import op

revision = "e8c4a1b67d02"
down_revision = "d3f8a2c61b47"
branch_labels = None
depends_on = None

# relkind r = ordinary table, p = partitioned table. Views have no RLS of
# their own; a view owned by a BYPASSRLS role would ignore RLS on the tables
# underneath, so those are switched to security_invoker. Materialized views
# cannot use RLS, so the anon/authenticated grants are revoked when those
# roles exist (they do on Supabase, not on a bare local Postgres).

_UPGRADE_SQL = """
DO $$
DECLARE
  r record;
  has_anon boolean;
  has_authenticated boolean;
BEGIN
  SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') INTO has_anon;
  SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated')
    INTO has_authenticated;

  FOR r IN
    SELECT n.nspname AS schema_name, c.relname AS rel_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
    ORDER BY c.relname
  LOOP
    EXECUTE format(
      'ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
      r.schema_name,
      r.rel_name
    );
  END LOOP;

  FOR r IN
    SELECT n.nspname AS schema_name, c.relname AS rel_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'v'
    ORDER BY c.relname
  LOOP
    EXECUTE format(
      'ALTER VIEW %I.%I SET (security_invoker = true)',
      r.schema_name,
      r.rel_name
    );
  END LOOP;

  IF has_anon OR has_authenticated THEN
    FOR r IN
      SELECT c.relname AS rel_name
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public'
        AND c.relkind = 'm'
      ORDER BY c.relname
    LOOP
      IF has_anon THEN
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon', r.rel_name);
      END IF;
      IF has_authenticated THEN
        EXECUTE format(
          'REVOKE ALL ON TABLE public.%I FROM authenticated',
          r.rel_name
        );
      END IF;
    END LOOP;
  END IF;
END $$;
"""

_DOWNGRADE_SQL = """
DO $$
DECLARE
  r record;
  has_anon boolean;
  has_authenticated boolean;
BEGIN
  SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') INTO has_anon;
  SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated')
    INTO has_authenticated;

  FOR r IN
    SELECT n.nspname AS schema_name, c.relname AS rel_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
    ORDER BY c.relname
  LOOP
    EXECUTE format(
      'ALTER TABLE %I.%I DISABLE ROW LEVEL SECURITY',
      r.schema_name,
      r.rel_name
    );
  END LOOP;

  FOR r IN
    SELECT n.nspname AS schema_name, c.relname AS rel_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'v'
    ORDER BY c.relname
  LOOP
    EXECUTE format(
      'ALTER VIEW %I.%I RESET (security_invoker)',
      r.schema_name,
      r.rel_name
    );
  END LOOP;

  IF has_anon OR has_authenticated THEN
    FOR r IN
      SELECT c.relname AS rel_name
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public'
        AND c.relkind = 'm'
      ORDER BY c.relname
    LOOP
      IF has_anon THEN
        EXECUTE format('GRANT ALL ON TABLE public.%I TO anon', r.rel_name);
      END IF;
      IF has_authenticated THEN
        EXECUTE format(
          'GRANT ALL ON TABLE public.%I TO authenticated',
          r.rel_name
        );
      END IF;
    END LOOP;
  END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
