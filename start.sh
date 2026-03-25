#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "[AILEX] Running Alembic migrations..."
alembic upgrade head

echo "[AILEX] Starting Uvicorn on 0.0.0.0:${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
