# syntax=docker/dockerfile:1

FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app

# Dependencies first, so a source-only change doesn't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project

COPY src/ ./src/
COPY data/ ./data/
RUN uv sync --no-dev

COPY --from=frontend /app/frontend/dist ./frontend/dist

ENV STATIC_DIR=/app/frontend/dist \
    PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000
CMD ["sh", "-c", "uvicorn climate_agent.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
