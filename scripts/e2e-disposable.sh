#!/bin/bash
# Disposable Postgres+Redis stack for the coop e2e lane (tests/e2e_disposable/).
#
# WHY: the shared test lane builds its schema from ORM metadata (never alembic)
# and shares one hardcoded DB name on :5433. This helper hands each lane its OWN
# throwaway containers on UNIQUE ephemeral ports so the lane can DROP SCHEMA and
# run `alembic upgrade head` for real without touching the shared dev DB — and,
# critically, without any chance of reaching Supabase PRODUCTION (the repo .env
# DATABASE_URL points there and migrations/env.py has no local-host guard).
#
# Usage:
#   ./scripts/e2e-disposable.sh <lane>                 # hold the stack, print URLs, Ctrl-C to tear down
#   ./scripts/e2e-disposable.sh <lane> -- <cmd...>     # run cmd with URLs exported, then tear down
#   ./scripts/e2e-disposable.sh <lane> --dsn <url>     # validate an override DSN (refuses non-localhost)
#   ./scripts/e2e-disposable.sh <lane> --dsn <url> --allow-remote
#
# Teardown is UNCONDITIONAL (trap EXIT INT TERM). Max 2 concurrent lanes.
set -euo pipefail

LANE="${1:-lane}"; shift || true
ALLOW_REMOTE=0
OVERRIDE_DSN=""
CMD=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-remote) ALLOW_REMOTE=1; shift;;
    --dsn) OVERRIDE_DSN="${2:-}"; shift 2;;
    --) shift; CMD=("$@"); break;;
    *) echo "ABORT: unknown argument '$1'" >&2; exit 2;;
  esac
done

# ── DSN refusal guard: never let a caller point this lane at a remote host ──
if [[ -n "$OVERRIDE_DSN" ]]; then
  host="$(printf '%s' "$OVERRIDE_DSN" | sed -n 's|^[a-zA-Z+]*://\([^/]*\)/.*$|\1|p' | sed 's/^.*@//' | sed 's/:[0-9]*$//')"
  if [[ -z "$host" ]]; then
    echo "ABORT: could not parse a host out of the override DSN — refusing." >&2; exit 1
  fi
  if [[ "$host" != "localhost" && "$host" != "127.0.0.1" && "$host" != "::1" ]]; then
    if [[ "$ALLOW_REMOTE" -ne 1 ]]; then
      echo "ABORT: DSN host '$host' is not localhost — refusing (pass --allow-remote if genuinely intended)." >&2
      exit 1
    fi
  fi
fi

# ── Docker binary resolution: the CLI is NOT on PATH on this machine ──
DOCKER=""
for cand in /Applications/Docker.app/Contents/Resources/bin/docker "$(command -v docker 2>/dev/null || true)"; do
  if [[ -n "$cand" && -x "$cand" ]]; then DOCKER="$cand"; break; fi
done
if [[ -z "$DOCKER" ]]; then
  echo "ABORT: docker CLI not found (checked /Applications/Docker.app/... and PATH)." >&2; exit 1
fi
if ! "$DOCKER" info >/dev/null 2>&1; then
  echo "ABORT: docker CLI found at $DOCKER but the DAEMON is not responding." >&2
  echo "       (This is a DIFFERENT failure from 'CLI not on PATH' — start Docker Desktop.)" >&2
  exit 1
fi

# ── Resource ceiling: at most 2 concurrent lanes (~1.0 GB with pytest RSS) ──
running_pairs="$("$DOCKER" ps --format '{{.Names}}' | grep -c '^e2e-.*-pg-' || true)"
if [[ "$running_pairs" -ge 2 ]]; then
  echo "ABORT: $running_pairs e2e-* postgres containers already running (ceiling is 2)." >&2; exit 1
fi

# ── Unique free host ports, never 5432/5433/6379/6543 ──
free_port() {
  python3 - <<'PY'
import socket
BANNED = {5432, 5433, 6379, 6543}
for _ in range(50):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    if p not in BANNED:
        print(p); break
else:
    raise SystemExit("no free port")
PY
}
PG_PORT="$(free_port)"
REDIS_PORT="$(free_port)"
PG_NAME="e2e-${LANE}-pg-${PG_PORT}"
REDIS_NAME="e2e-${LANE}-redis-${REDIS_PORT}"

teardown() {
  "$DOCKER" rm -f "$PG_NAME" "$REDIS_NAME" >/dev/null 2>&1 || true
}
trap teardown EXIT INT TERM

"$DOCKER" run -d --rm --name "$PG_NAME" \
  -e POSTGRES_USER=e2e -e POSTGRES_PASSWORD=e2e -e POSTGRES_DB=e2e \
  -p "127.0.0.1:${PG_PORT}:5432" \
  --tmpfs /var/lib/postgresql/data:rw \
  postgres:16-alpine -c fsync=off -c full_page_writes=off >/dev/null
"$DOCKER" run -d --rm --name "$REDIS_NAME" \
  -p "127.0.0.1:${REDIS_PORT}:6379" redis:7-alpine >/dev/null

# ── Bounded readiness poll ──
for i in $(seq 1 60); do
  if "$DOCKER" exec "$PG_NAME" pg_isready -U e2e -d e2e >/dev/null 2>&1; then break; fi
  if [[ "$i" -eq 60 ]]; then echo "ABORT: postgres not ready after 60s." >&2; exit 1; fi
  sleep 1
done
for i in $(seq 1 30); do
  if "$DOCKER" exec "$REDIS_NAME" redis-cli ping >/dev/null 2>&1; then break; fi
  if [[ "$i" -eq 30 ]]; then echo "ABORT: redis not ready after 30s." >&2; exit 1; fi
  sleep 1
done

DATABASE_URL="postgresql+asyncpg://e2e:e2e@localhost:${PG_PORT}/e2e"
REDIS_URL="redis://localhost:${REDIS_PORT}/0"
echo "DATABASE_URL=${DATABASE_URL}"
echo "REDIS_URL=${REDIS_URL}"

if [[ ${#CMD[@]} -gt 0 ]]; then
  set +e
  DATABASE_URL="$DATABASE_URL" REDIS_URL="$REDIS_URL" E2E_DISPOSABLE=1 "${CMD[@]}"
  rc=$?
  set -e
  exit $rc
fi

# No command: hold the stack so another terminal can export and run pytest.
# Ctrl-C (SIGINT) fires the trap and removes both containers.
echo "# holding stack — Ctrl-C to tear down" >&2
while true; do sleep 1; done
