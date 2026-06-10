# ============================================================
# RecoverFlow AI — Backend Dockerfile
# Multi-purpose image for both FastAPI API and Celery Worker.
# Usage:
#   API:    CMD ["uvicorn", "main:app", ...]
#   Worker: CMD ["celery", "-A", "tasks", "worker", ...]
# ============================================================

FROM python:3.13-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ── System Dependencies ─────────────────────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Python Dependencies ─────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Application Code ────────────────────────────────────────
COPY . .

# ── Default: Run FastAPI via Uvicorn ─────────────────────────
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
