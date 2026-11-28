FROM python:3.12-slim@sha256:5b5fe805d367f8f5a359ded6ab2652b7f9a206453ee6ee789c0045ba6ec15016

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    ca-certificates \
    python3-poetry \
    python3-venv \
  && rm -rf /var/lib/apt/lists/*

# The lock is part of the build: without it the build stops instead of
# resolving whatever versions are newest that day.
COPY pyproject.toml poetry.lock /app/

# Make poetry put the venv in /app/.venv and use the image's Python
RUN poetry config virtualenvs.in-project true \
 && poetry env use /usr/local/bin/python \
 && poetry install --no-interaction --no-ansi --only main --no-root

# Make the venv the default Python for runtime
ENV PATH="/app/.venv/bin:$PATH"

COPY app /app/app
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY scripts /app/scripts

RUN chmod +x /app/scripts/start.sh /app/scripts/start-celery-worker.sh /app/scripts/start-celery-beat.sh

# Create non-root runtime user
RUN addgroup --system --gid 10001 midena \
 && adduser --system --uid 10001 --ingroup midena --home /home/midena midena \
 && mkdir -p /var/lib/midena \
 && chown -R midena:midena /app /var/lib/midena

USER midena
ENV HOME=/home/midena

CMD ["/app/scripts/start.sh"]
