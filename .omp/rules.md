# oh-my-pi Project Rules

## Environment
- Python venv at `.venv/` — activate before running Python
- Node modules in `apps/web/node_modules/`
- Environment variables in `.env` (never commit secrets)

## Commands
- **API server:** `cd apps/api && uvicorn main:app --reload --port 8000`
- **Web dev:** `cd apps/web && npm run dev`
- **Celery worker:** `cd apps/api && celery -A services.celery_app worker -l info`
- **DB migrations:** `cd apps/api && alembic upgrade head`
- **Tests:** `cd apps/api && pytest`

## LSP Setup
- Python: use pyright or pylsp pointed at `apps/api/`
- TypeScript: tsserver via `apps/web/tsconfig.json`

## Edit Preferences
- Prefer small, focused edits over large rewrites
- Always run type checks after editing Python (pyright) or TypeScript (tsc --noEmit)
- Test after every significant change

## Do Not
- Modify .env with real API keys in commits
- Skip the implementation order in PRODUCT_ROADMAP.md
- Use print() in Python — use structlog
- Use `any` type in TypeScript
- Add dependencies without checking if existing ones suffice
