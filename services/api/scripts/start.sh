#!/usr/bin/env bash
set -euo pipefail

cd /app
export PATH="/app/.venv/bin:$PATH"
export PYTHONPATH="${PYTHONPATH:-/app}"
: "${MIDENA_DATABASE_URL:?MIDENA_DATABASE_URL is required}"

echo "[midena-api] waiting for database..."
python - <<'PYCODE'
import os, time
import sqlalchemy as sa

url = os.environ['MIDENA_DATABASE_URL']
engine = sa.create_engine(url, pool_pre_ping=True)
deadline = time.time() + 60
while True:
    try:
        with engine.connect() as c:
            c.execute(sa.text('SELECT 1'))
        print('[midena-api] database ready')
        break
    except Exception:
        if time.time() > deadline:
            raise
        time.sleep(1)
PYCODE

echo "[midena-api] running migrations..."
alembic upgrade head

echo "[midena-api] starting uvicorn..."
# Forwarded headers are read by the application, from MIDENA_SECURITY_TRUSTED_PROXY_CIDRS
# only (app/security/client_addr.py); the server's own rewriting stays off.
exec uvicorn app.main:app --host "${MIDENA_API_HOST:-0.0.0.0}" --port "${MIDENA_API_PORT:-8080}" --no-proxy-headers
