# syntax=docker/dockerfile:1.7

FROM python:3.13-slim-bookworm AS python-build

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

ENV DATA_DIR=/var/lib/open-sports-analyst \
    PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
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

RUN uv sync --frozen --no-dev --no-editable \
    && JOB_BACKEND=local PERSISTENCE_BACKEND=local DATA_DIR=/tmp/container-smoke sports-analyst capabilities \
    && python -c "import sports_analyst.worker"

# Build the complete, locked analysis environment without pulling in the
# frontend stage. The deployed Job only needs the installed Python environment.
FROM python-build AS cloud-analysis-build
RUN uv sync --frozen --no-dev --no-editable --extra cloud-run

FROM python:3.13-slim-bookworm AS cloud-analysis
ENV DATA_DIR=/tmp/open-sports-analyst
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 analyst \
    && useradd --uid 10001 --gid analyst --create-home analyst \
    && mkdir -p /app "$DATA_DIR" \
    && chown -R analyst:analyst /app "$DATA_DIR"

WORKDIR /app
COPY --from=cloud-analysis-build --chown=analyst:analyst /app/.venv/ /app/.venv/
USER analyst
RUN python -c "import boto3, google.auth, vl_convert; import sports_analyst.service, sports_analyst.worker, sports_analyst.reports, sports_analyst.analysis_api; from sports_analyst.nba_data import SportsDataverseNBAConnector; SportsDataverseNBAConnector()"


FROM node:24-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python-build AS runtime
COPY --chown=analyst:analyst --from=frontend-build /build/frontend/dist/ ./frontend/dist/
ENV SPORTS_ANALYST_FRONTEND_DIR=/app/frontend/dist
USER analyst
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3).read()"]

CMD ["sports-analyst", "serve", "--host", "0.0.0.0", "--port", "8080"]


# The public API and sync target intentionally omit model-provider, tracing,
# chart-rendering, and desktop dependencies. They enqueue durable work and
# manipulate datasets but never execute model analysis themselves.
FROM python:3.13-slim-bookworm AS cloud-lite

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

ENV DATA_DIR=/tmp/open-sports-analyst \
    PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
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
COPY --chown=analyst:analyst pyproject.toml README.md LICENSE NOTICE ./
COPY --chown=analyst:analyst src/ ./src/

RUN uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python \
      "boto3>=1.42,<2" "duckdb>=1.4,<2" "fastapi[standard]>=0.141.1" \
      "google-auth[requests]>=2.58,<3" "nflreadpy>=0.1.5,<0.2" "numpy>=2.3,<3" \
      "platformdirs>=4.4,<5" "polars>=1.34,<2" "pyarrow>=25.0.1" \
      "pydantic>=2.11,<3" "pydantic-settings>=2.11,<3" "python-dotenv>=1.1,<2" \
      "sportsdataverse>=0.0.75,<0.1" "typer>=0.19,<1" "tzdata>=2025.2" "uvicorn[standard]>=0.37" \
    && uv pip install --python /app/.venv/bin/python --no-deps .

USER analyst
EXPOSE 8080

FROM cloud-lite AS cloud-sync
CMD ["uvicorn", "sports_analyst.sync_api:app", "--host", "0.0.0.0", "--port", "8080"]

FROM cloud-lite AS cloud-api
COPY --chown=analyst:analyst --from=frontend-build /build/frontend/dist/ ./frontend/dist/
ENV SPORTS_ANALYST_FRONTEND_DIR=/app/frontend/dist \
    SPORTS_ANALYST_RUNTIME_ROLE=api
CMD ["sports-analyst", "serve", "--host", "0.0.0.0", "--port", "8080"]

# Preserve the original all-in-one target for external self-hosting scripts.
FROM runtime AS cloud-run
USER root
RUN uv sync --frozen --no-dev --no-editable --extra cloud-run
ENV DATA_DIR=/tmp/open-sports-analyst
USER analyst
