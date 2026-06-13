# Pin to Debian Bookworm (12). The bare `slim` tag now resolves to Trixie (13),
# which Playwright 1.49 doesn't recognize — its `--with-deps` then falls back to
# obsolete Ubuntu 20.04 font package names (ttf-unifont, ttf-ubuntu-font-family)
# that don't exist, failing the build. Bookworm is a Playwright-supported OS.
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install dependencies (pinned root requirements)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

# Copy app code
COPY apps/api/ ./apps/api/

# Copy pixel for serving tracker.js
COPY apps/pixel/ ./apps/pixel/

# Set Python path so apps.api module resolves
ENV PYTHONPATH=/app

EXPOSE 8000

# Run DB migrations before serving. Prod is stamped at the Alembic baseline, so
# this is a no-op until a new migration is added. A failing migration fails the
# deploy (Railway keeps the previous version serving) instead of booting the app
# against a wrong schema.
CMD python -m alembic -c apps/api/alembic.ini upgrade head && uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
