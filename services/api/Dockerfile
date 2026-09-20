FROM python:3.12-slim

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

COPY pyproject.toml poetry.lock* /app/

RUN poetry config virtualenvs.in-project true \
 && poetry env use /usr/local/bin/python \
 && if [ -f poetry.lock ]; then \
      poetry install --no-interaction --no-ansi --only main --no-root; \
    else \
      poetry lock --no-interaction --no-ansi \
   && poetry install --no-interaction --no-ansi --only main --no-root; \
    fi

ENV PATH="/app/.venv/bin:$PATH"

COPY app /app/app
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY scripts /app/scripts

RUN chmod +x /app/scripts/start.sh /app/scripts/start-celery-worker.sh /app/scripts/start-celery-beat.sh

RUN addgroup --system --gid 10001 midena \
 && adduser --system --uid 10001 --ingroup midena --home /home/midena midena \
 && mkdir -p /var/lib/midena \
 && chown -R midena:midena /app /var/lib/midena

USER midena
ENV HOME=/home/midena

CMD ["/app/scripts/start.sh"]
