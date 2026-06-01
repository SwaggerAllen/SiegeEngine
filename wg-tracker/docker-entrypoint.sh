#!/usr/bin/env bash
# Container entrypoint. ROLE selects the behavior so a single image backs every
# App Platform component (web service, scheduled job, migration job).
set -euo pipefail

ROLE="${ROLE:-web}"

run_migrations() {
  echo '{"msg":"running alembic migrations"}'
  alembic upgrade head
}

case "$ROLE" in
  migrate)
    run_migrations
    ;;
  web)
    # Run migrations on startup so a fresh deploy is immediately usable, then serve.
    run_migrations
    exec uvicorn wgtracker.web.app:app \
      --host 0.0.0.0 --port "${PORT:-8000}" \
      --proxy-headers --forwarded-allow-ips='*'
    ;;
  pipeline)
    # Scheduled ingestion + processing job. Pass extra args through, e.g.
    #   ROLE=pipeline ... docker run image --wg mls --since 2025-05-01
    run_migrations
    exec wgtracker ingest "$@"
    ;;
  mcp)
    exec python -m wgtracker.mcp_server
    ;;
  *)
    echo "Unknown ROLE: $ROLE (expected web|pipeline|migrate|mcp)" >&2
    exit 1
    ;;
esac
