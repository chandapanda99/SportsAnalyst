# syntax=docker/dockerfile:1.7

FROM node:24-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.13-slim-bookworm AS python-runtime

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

ENV DATA_DIR=/var/lib/open-sports-analyst \
    PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SPORTS_ANALYST_FRONTEND_DIR=/app/frontend/dist \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 analyst \
    && useradd --uid 10001 --gid analyst --create-home analyst \
    && mkdir -p /app "$DATA_DIR" \
    && chown -R analyst:analyst /app "$DATA_DIR"

WORKDIR /app

# Install locked third-party packages before copying frequently changing source.
COPY --chown=analyst:analyst pyproject.toml uv.lock README.md LICENSE NOTICE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=analyst:analyst src/ ./src/
COPY --chown=analyst:analyst migrations/ ./migrations/
COPY --chown=analyst:analyst alembic.ini ./
COPY --chown=analyst:analyst --from=frontend-build /build/frontend/dist/ ./frontend/dist/

RUN uv sync --frozen --no-dev --no-editable \
    && JOB_BACKEND=local PERSISTENCE_BACKEND=local DATA_DIR=/tmp/container-smoke sports-analyst capabilities \
    && python -c "import boto3, psycopg, sqlalchemy.dialects.postgresql.psycopg, sports_analyst.worker"

USER analyst
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3).read()"]

CMD ["sports-analyst", "serve", "--host", "0.0.0.0", "--port", "8080"]

FROM python-runtime AS cloud-run
USER root
RUN uv sync --frozen --no-dev --no-editable --extra cloud-run
ENV DATA_DIR=/tmp/open-sports-analyst
USER analyst
