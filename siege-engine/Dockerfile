# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build
ARG COMMIT_HASH=unknown
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_COMMIT_HASH=$COMMIT_HASH
RUN npm run build

# Stage 2: Runtime
FROM python:3.11-slim
WORKDIR /app

# Install system deps: Node.js (required for Claude CLI), git, gosu
RUN apt-get update && apt-get install -y curl git gosu && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Claude CLI (separate layer for caching — only rebuilds when CLI version changes)
RUN npm install -g @anthropic-ai/claude-code

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy backend code
COPY backend/ ./backend/

# Copy the new MCP server library (read-only state surface + writer CLI).
# Mounted by backend.main at /siege_mcp; also runnable standalone via
# `python -m siege_mcp.server`.
COPY siege_mcp/ ./siege_mcp/

# Copy Alembic migration files
COPY alembic.ini ./
COPY alembic/ ./alembic/

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Create non-root user (Claude CLI refuses --dangerously-skip-permissions as root)
RUN useradd -m -s /bin/bash claude

# Create data directory (will be mounted as volume in production)
RUN mkdir -p /data/repos && chown -R claude:claude /data

# Ensure app directory is readable
RUN chown -R claude:claude /app

# Default environment variables
ARG COMMIT_HASH=unknown
ENV COMMIT_HASH=$COMMIT_HASH
ENV SIEGE_DATABASE_URL=sqlite:////data/siege_engine.db
ENV SIEGE_GIT_REPOS_BASE_PATH=/data/repos

EXPOSE 8000
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]
