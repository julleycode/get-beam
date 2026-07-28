#!/usr/bin/env bash
# Start Beam local stack on macOS / Linux (Docker PG+Redis + API + Web + demo user).
#
# Usage:
#   ./scripts/dev-local.sh
#   ./scripts/dev-local.sh --skip-install
#   ./scripts/dev-local.sh --migrate-only
#   ./scripts/dev-local.sh --no-browser
#   ./scripts/dev-local.sh --full-seed
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

SKIP_INSTALL=0
MIGRATE_ONLY=0
NO_BROWSER=0
FULL_SEED=0
for arg in "$@"; do
  case "$arg" in
    --skip-install) SKIP_INSTALL=1 ;;
    --migrate-only) MIGRATE_ONLY=1 ;;
    --no-browser) NO_BROWSER=1 ;;
    --full-seed) FULL_SEED=1 ;;
    -h|--help)
      sed -n '1,12p' "$0"
      exit 0
      ;;
  esac
done

step() { printf '\033[0;36m[dev-local]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[dev-local]\033[0m %s\n' "$*"; }
fail() { printf '\033[0;31m[dev-local]\033[0m %s\n' "$*" >&2; exit 1; }

# ─── Env files ───────────────────────────────────────────
if [[ ! -f "$ROOT_DIR/.env" ]]; then
  [[ -f "$ROOT_DIR/.env.example" ]] || fail "Missing .env.example"
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  step "Created .env from .env.example"
else
  step "Using existing .env"
fi

if [[ ! -f "$ROOT_DIR/apps/web/.env.local" ]]; then
  [[ -f "$ROOT_DIR/apps/web/.env.example" ]] || fail "Missing apps/web/.env.example"
  cp "$ROOT_DIR/apps/web/.env.example" "$ROOT_DIR/apps/web/.env.local"
  step "Created apps/web/.env.local from .env.example"
else
  step "Using existing apps/web/.env.local"
fi

if grep -Eiq 'supabase|railway\.app|amazonaws\.com' "$ROOT_DIR/.env"; then
  fail "ABORT: .env DATABASE_URL looks remote. Point it at localhost:5433 for local dev."
fi
if grep -q 'DATABASE_URL=' "$ROOT_DIR/.env" && ! grep -q 'localhost:5433' "$ROOT_DIR/.env"; then
  warn "DATABASE_URL should use localhost:5433 (Docker). Native Postgres often owns :5432."
fi

# ─── Docker ──────────────────────────────────────────────
step "Starting Docker postgres (:5433) + redis..."
docker compose -f infra/docker-compose.yml up -d postgres redis

step "Waiting for Docker Postgres on :5433..."
ready=0
for _ in $(seq 1 40); do
  if command -v pg_isready >/dev/null 2>&1; then
    pg_isready -h localhost -p 5433 >/dev/null 2>&1 && ready=1 && break
  else
    nc -z localhost 5433 >/dev/null 2>&1 && ready=1 && break
  fi
  sleep 1
done
[[ "$ready" -eq 1 ]] || fail "Postgres not reachable on localhost:5433"
step "Postgres is up on :5433"

# ─── Python venv ─────────────────────────────────────────
if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  step "Creating .venv..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source "$ROOT_DIR/.venv/bin/activate"

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  step "Installing Python deps (requirements.txt)..."
  pip install -r "$ROOT_DIR/requirements.txt"
fi

# ─── Migrate + demo user ─────────────────────────────────
step "Running alembic upgrade head..."
export PYTHONPATH="$ROOT_DIR"
python -m alembic -c apps/api/alembic.ini upgrade head

step "Ensuring demo user (demo@getbeam.fyi / password123)..."
python -m scripts.ensure_demo_user

if [[ "$FULL_SEED" -eq 1 ]]; then
  step "Full seed (visitors/campaigns)..."
  python -m scripts.seed || warn "Full seed failed (demo user still OK)"
fi

if [[ "$MIGRATE_ONLY" -eq 1 ]]; then
  step "Migrate + demo user done."
  exit 0
fi

if [[ "$SKIP_INSTALL" -eq 0 || ! -d "$ROOT_DIR/apps/web/node_modules" ]]; then
  step "Installing web deps (npm)..."
  (cd "$ROOT_DIR/apps/web" && npm install)
fi

# ─── Start API + Web ─────────────────────────────────────
API_LOG="$ROOT_DIR/.dev-local-api.log"
WEB_LOG="$ROOT_DIR/.dev-local-web.log"
PID_FILE="$ROOT_DIR/.dev-local.pids"

cleanup() {
  if [[ -f "$PID_FILE" ]]; then
    while read -r pid; do
      kill "$pid" 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
}
trap cleanup EXIT INT TERM

: > "$PID_FILE"

step "Starting API (uvicorn :8000) → $API_LOG"
(
  cd "$ROOT_DIR"
  export PYTHONPATH="$ROOT_DIR"
  exec "$ROOT_DIR/.venv/bin/python" -m uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
) >"$API_LOG" 2>&1 &
echo $! >> "$PID_FILE"

step "Waiting for API /health..."
api_ok=0
for _ in $(seq 1 60); do
  if curl -sf "http://localhost:8000/health" >/dev/null 2>&1; then api_ok=1; break; fi
  sleep 1
done
[[ "$api_ok" -eq 1 ]] && step "API is healthy" || warn "API health not ready — check $API_LOG"

step "Starting Web (Next.js :3000) → $WEB_LOG"
(
  cd "$ROOT_DIR/apps/web"
  exec npm run dev
) >"$WEB_LOG" 2>&1 &
echo $! >> "$PID_FILE"

step "Waiting for Web /login..."
web_ok=0
for _ in $(seq 1 90); do
  if curl -sf "http://localhost:3000/login" >/dev/null 2>&1; then web_ok=1; break; fi
  sleep 1
done
[[ "$web_ok" -eq 1 ]] && step "Web is up" || warn "Web not ready yet — check $WEB_LOG"

if [[ "$NO_BROWSER" -eq 0 ]]; then
  if command -v open >/dev/null 2>&1; then
    open "http://localhost:3000/login" || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:3000/login" || true
  fi
fi

step "Local stack ready."
echo "  API:   http://localhost:8000/health"
echo "  Login: http://localhost:3000/login"
echo "  Demo:  demo@getbeam.fyi / password123"
echo "  Logs:  $API_LOG , $WEB_LOG"
echo ""
warn "Press Ctrl+C to stop API + Web. Docker: docker compose -f infra/docker-compose.yml stop"

wait
