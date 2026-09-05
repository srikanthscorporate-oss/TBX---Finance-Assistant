# syntax=docker/dockerfile:1
#
# Build context is the REPOSITORY ROOT (see docker-compose.yml): the image needs
# both apps/api and the top-level prompts/ directory.

FROM ghcr.io/astral-sh/uv:0.5-python3.12-bookworm-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TBX_PROMPT_DIR=/srv/prompts \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/srv/.venv \
    PATH="/srv/.venv/bin:$PATH"

WORKDIR /srv

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Dependencies resolve from the lockfile in their own layer, so a source edit
# does not trigger a reinstall.
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY apps/api/app ./app
COPY apps/api/tests ./tests
COPY prompts /srv/prompts
# The canonical DDL: services/ingest.py replays it when a user-supplied MySQL
# source is initialised, so the ingested shape cannot drift from the schema file.
COPY infra/clickhouse/001_schema.sql /srv/infra/clickhouse/001_schema.sql

RUN useradd --system --uid 10001 --home /srv tbx \
 && chown -R tbx:tbx /srv
USER tbx

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
