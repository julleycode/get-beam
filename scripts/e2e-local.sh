#!/bin/bash
# Safe LOCAL Playwright e2e runner.
#
# WHY THIS EXISTS: playwright.config.ts starts the backend (uvicorn) with NO env
# override, so it reads the root .env = PRODUCTION Supabase DB. The frontend's
# web/.env.local also points NEXT_PUBLIC_API_URL at the PRODUCTION Railway API.
# Running `npx playwright test` raw would therefore read/WRITE PRODUCTION.
#
# This script forces every server to the LOCAL docker stack (env vars override
# .env / .env.local) and HARD-REFUSES to run if anything still looks remote.
#
# Usage:
#   ./scripts/e2e-local.sh                 # all specs, headless
#   ./scripts/e2e-local.sh --headed        # watch the browser
#   ./scripts/e2e-local.sh visitors.spec.ts
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# ── Force the LOCAL stack (env vars take precedence over .env / .env.local) ──
export DATABASE_URL="postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent"
export REDIS_URL="redis://localhost:6379/0"
export APP_ENV="development"
export NEXT_PUBLIC_API_URL="http://localhost:8000"

# ── SAFETY GUARD: never touch anything but localhost ──
for v in DATABASE_URL REDIS_URL NEXT_PUBLIC_API_URL; do
  val="${!v}"
  if [[ "$val" != *localhost* && "$val" != *127.0.0.1* ]]; then
    echo "ABORT: $v is not local ($val) — refusing to run e2e against a remote host." >&2
    exit 1
  fi
done
case "$DATABASE_URL" in
  *supabase*|*pooler*|*railway*|*amazonaws*)
    echo "ABORT: DATABASE_URL looks like production. Refusing." >&2; exit 1;;
esac
echo "[e2e-local] DB=$DATABASE_URL"
echo "[e2e-local] API=$NEXT_PUBLIC_API_URL   (local only ✓)"

# ── Bring up local postgres + redis if not already running ──
pg_ready() {
  if command -v pg_isready >/dev/null 2>&1; then pg_isready -h localhost -p 5433 >/dev/null 2>&1
  else nc -z localhost 5433 >/dev/null 2>&1; fi
}
if ! pg_ready; then
  echo "[e2e-local] starting docker postgres + redis..."
  docker compose -f infra/docker-compose.yml up -d postgres redis
  for _ in $(seq 1 30); do pg_ready && break; sleep 1; done
fi
pg_ready || { echo "ABORT: local postgres not reachable on :5433 (is Docker running?)." >&2; exit 1; }

# ── Playwright browser (first run installs chromium) ──
( cd apps/web && (npx playwright install --check chromium >/dev/null 2>&1 || npx playwright install chromium) )

# ── Run e2e — playwright.config starts the LOCAL uvicorn + next dev ──
echo "[e2e-local] running Playwright..."
cd apps/web
npx playwright test "$@"
