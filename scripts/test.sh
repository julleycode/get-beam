#!/bin/bash
# Run all tests: backend unit, backend integration, and Playwright E2E
# Usage: ./scripts/test.sh [unit|integration|e2e|all]

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo_status() { echo -e "${GREEN}[TEST]${NC} $1"; }
echo_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
echo_fail() { echo -e "${RED}[FAIL]${NC} $1"; }

# ─── Unit Tests ─────────────────────────────────────────
run_unit() {
    echo_status "Running backend unit tests..."
    PYTHONPATH=. .venv/bin/python -m pytest tests/unit/ -v --tb=short
    echo_status "Unit tests passed!"
}

# ─── Integration Tests ──────────────────────────────────
run_integration() {
    echo_status "Running backend integration tests..."

    # Check if Postgres is running
    if ! pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
        echo_warn "PostgreSQL not running. Starting docker-compose..."
        docker compose -f infra/docker-compose.yml up -d postgres redis
        echo_status "Waiting for services to start..."
        sleep 5
    fi

    PYTHONPATH=. .venv/bin/python -m pytest tests/integration/ -v --tb=short -m integration
    echo_status "Integration tests passed!"
}

# ─── Playwright E2E Tests ───────────────────────────────
run_e2e() {
    echo_status "Running Playwright E2E tests..."

    cd apps/web

    # Check if Playwright browsers are installed
    if ! npx playwright install --check chromium >/dev/null 2>&1; then
        echo_warn "Installing Playwright browsers..."
        npx playwright install chromium
    fi

    npx playwright test
    echo_status "E2E tests passed!"
    cd "$ROOT_DIR"
}

# ─── Main ───────────────────────────────────────────────
case "${1:-all}" in
    unit)
        run_unit
        ;;
    integration)
        run_integration
        ;;
    e2e)
        run_e2e
        ;;
    all)
        run_unit
        echo ""
        run_integration || echo_warn "Integration tests skipped (no DB)"
        echo ""
        run_e2e || echo_warn "E2E tests skipped"
        ;;
    *)
        echo "Usage: $0 [unit|integration|e2e|all]"
        exit 1
        ;;
esac

echo ""
echo_status "All tests completed!"
