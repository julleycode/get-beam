#!/bin/bash
# ============================================================
#  ReTargetAgent — Round 3 launcher
#  Fixes: asyncpg Python 3.14 compile fail + Redis port conflict
# ============================================================
set -e
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║    ReTargetAgent — Round 3 Start         ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Find project folder ───────────────────────────────────
echo "🔍  Looking for 'retargeting user' folder..."
PROJECT=""
for CANDIDATE in \
    "$HOME/Downloads/retargeting user" \
    "$HOME/Desktop/retargeting user" \
    "$HOME/Documents/retargeting user" \
    "$HOME/retargeting user"; do
    if [ -d "$CANDIDATE" ]; then
        PROJECT="$CANDIDATE"
        break
    fi
done
if [ -z "$PROJECT" ]; then
    PROJECT=$(find "$HOME" -maxdepth 4 -type d -name "retargeting user" 2>/dev/null | head -1)
fi
if [ -z "$PROJECT" ]; then
    echo "❌  Could not find project folder. Drag it here and press Enter:"
    read -r PROJECT
    PROJECT="${PROJECT%/}"
fi
echo "✅  Found: $PROJECT"
echo ""

# ── 2. Fix resend version in requirements.txt ────────────────
REQ="$PROJECT/apps/api/requirements.txt"
if [ -f "$REQ" ] && grep -q "resend==2\.5\.0" "$REQ"; then
    sed -i '' 's/resend==2\.5\.0/resend>=2.0.0/' "$REQ"
    echo "🔧  Patched resend version"
fi

# ── 3. Kill ALL Docker containers (free every port) ──────────
echo "🐳  Ensuring Docker is running..."
open -a Docker 2>/dev/null || true
for i in $(seq 1 30); do
    if docker info &>/dev/null; then break; fi
    sleep 1; echo -n "."
done
echo ""
docker info &>/dev/null || { echo "❌  Docker not running."; exit 1; }

echo "🔴  Stopping ALL running containers (frees all ports)..."
RUNNING=$(docker ps -q 2>/dev/null)
if [ -n "$RUNNING" ]; then
    docker stop $RUNNING 2>/dev/null || true
fi
echo "🔄  Removing infra containers..."
cd "$PROJECT/infra"
docker compose down 2>/dev/null || true
sleep 2

echo "🗄️   Starting PostgreSQL, Redis, ClickHouse..."
docker compose up -d 2>&1 | tail -10
echo ""

# ── 4. Wait for Postgres (dynamic name) ──────────────────────
echo "⏳  Waiting for PostgreSQL to be healthy (up to 90s)..."
PG_HEALTHY=0
for i in $(seq 1 90); do
    PG_NAME=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -iE 'postgres' | head -1)
    if [ -n "$PG_NAME" ]; then
        STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$PG_NAME" 2>/dev/null || echo "none")
        if [ "$STATUS" = "healthy" ]; then
            PG_HEALTHY=1
            echo ""
            echo "✅  PostgreSQL healthy ($PG_NAME)"
            break
        fi
    fi
    sleep 1; echo -n "."
done
if [ "$PG_HEALTHY" = "0" ]; then
    echo ""
    echo "⚠️   Postgres health check timed out — continuing anyway."
fi
echo ""

# ── 5. Pick best Python (prefer 3.11 or 3.12 for binary wheels) ──
echo "🐍  Finding best Python version..."
PYTHON=""
for PY in python3.12 python3.11 python3.10 python3; do
    if command -v "$PY" &>/dev/null; then
        VER=$("$PY" -c "import sys; print(sys.version_info[:2])")
        echo "    Found: $PY ($VER)"
        PYTHON=$(command -v "$PY")
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "❌  No Python 3 found."; exit 1
fi

# Remove old venv if it used a bad Python version
VENV="$PROJECT/.venv"
cd "$PROJECT"
if [ -d "$VENV" ]; then
    VENV_PY=$("$VENV/bin/python" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    echo "    Existing venv Python: $VENV_PY"
    # Remove if Python 3.14 (asyncpg won't build)
    if echo "$VENV_PY" | grep -q "^3\.14"; then
        echo "🗑️   Removing Python 3.14 venv (asyncpg incompatible)..."
        rm -rf "$VENV"
    fi
fi

if [ ! -d "$VENV" ]; then
    echo "🐍  Creating Python virtual environment with $PYTHON..."
    "$PYTHON" -m venv "$VENV"
fi

echo "📦  Installing Python dependencies (--prefer-binary skips C compilation)..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --prefer-binary --quiet -r apps/api/requirements.txt
echo "✅  Python deps installed."
echo ""

# ── 6. Seed the database ─────────────────────────────────────
echo "🌱  Seeding database..."
PYTHONPATH="$PROJECT" "$VENV/bin/python" -m scripts.seed 2>&1 || {
    echo "⚠️   Seed already done or skipped — continuing."
}
echo "✅  Database ready."
echo ""

# ── 7. Start API ─────────────────────────────────────────────
echo "🚀  Starting FastAPI on http://localhost:8000 ..."
API_CMD="cd '$PROJECT' && PYTHONPATH='$PROJECT' '$VENV/bin/uvicorn' apps.api.main:app --host 0.0.0.0 --port 8000 --reload"
osascript -e "
tell application \"Terminal\"
    activate
    tell application \"System Events\" to keystroke \"t\" using command down
    delay 0.5
    do script \"$API_CMD\" in front window
end tell
" 2>/dev/null || true

# ── 8. Start Next.js ─────────────────────────────────────────
echo "🌐  Starting Next.js on http://localhost:3000 ..."
WEB_DIR="$PROJECT/apps/web"
if [ ! -d "$WEB_DIR/node_modules" ]; then
    echo "📦  Installing npm dependencies (first run ~2 min)..."
    cd "$WEB_DIR" && npm install --silent
fi
WEB_CMD="cd '$WEB_DIR' && npm run dev"
osascript -e "
tell application \"Terminal\"
    activate
    tell application \"System Events\" to keystroke \"t\" using command down
    delay 0.5
    do script \"$WEB_CMD\" in front window
end tell
" 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ✅  ReTargetAgent is launching!          ║"
echo "║                                           ║"
echo "║  Dashboard  → http://localhost:3000       ║"
echo "║  API docs   → http://localhost:8000/docs  ║"
echo "╚══════════════════════════════════════════╝"
echo ""
sleep 5
open "http://localhost:3000" 2>/dev/null || true
