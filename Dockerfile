FROM python:3.11-slim

WORKDIR /app

# System deps for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
    libasound2 libatspi2.0-0 libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt bcrypt cryptography \
    && playwright install chromium

# Copy app code
COPY apps/api/ ./apps/api/

# Copy pixel for serving tracker.js
COPY apps/pixel/ ./apps/pixel/

# Set Python path so apps.api module resolves
ENV PYTHONPATH=/app

EXPOSE 8000

CMD uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
