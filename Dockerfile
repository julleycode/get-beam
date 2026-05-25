FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt bcrypt cryptography

# Copy app code
COPY apps/api/ ./apps/api/

# Copy pixel for serving tracker.js
COPY apps/pixel/ ./apps/pixel/

# Set Python path so apps.api module resolves
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
