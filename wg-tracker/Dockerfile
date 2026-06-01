# Multi-stage build to keep the runtime image small.
# Stage 1: build a self-contained virtualenv with all dependencies + the package.
FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# uv for fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies first (cached layer), then the project.
COPY pyproject.toml README.md ./
COPY wgtracker ./wgtracker
RUN uv pip install --python /opt/venv/bin/python .

# Stage 2: slim runtime.
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    CONFIG_PATH=/app/config.yaml

# Non-root runtime user.
RUN useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY wgtracker ./wgtracker
COPY alembic ./alembic
COPY alembic.ini config.yaml docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

# ROLE selects the component behavior (web | pipeline | migrate | mcp).
ENV ROLE=web
ENTRYPOINT ["./docker-entrypoint.sh"]
