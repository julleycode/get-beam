# ReTargetAgent

AI-powered retargeting agent that identifies anonymous website visitors, enriches their profiles, and auto-generates personalized campaigns.

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+
- Docker & Docker Compose

### 1. Start infrastructure
```bash
cd infra
docker-compose up -d
```

### 2. Start the API
```bash
cd apps/api
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Seed test data (requires running Postgres + ClickHouse)
python -m scripts.seed
# Start the server
uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Start the dashboard
```bash
cd apps/web
npm install
npm run dev
```

### 4. Start Celery workers (optional, for background jobs)
```bash
cd apps/api
celery -A apps.api.services.celery_app worker -l info
celery -A apps.api.services.celery_app beat -l info
```

### Demo credentials
- Email: `demo@retargetagent.com`
- Password: `password123`

## Architecture
```
Website with Pixel → Event Collector API → Identity Resolution
→ Enrichment → AI Segmentation → Campaign Planner → Dashboard
```

## Tech Stack
- **Frontend**: Next.js 14 + Tailwind CSS + shadcn/ui
- **Backend**: Python FastAPI
- **Pixel**: Vanilla JS (<5KB)
- **Database**: PostgreSQL + ClickHouse
- **Queue**: Celery + Redis
- **AI**: Claude API for segmentation & campaign planning
