#!/bin/bash
set -e

# Fix /data ownership — Fly.io volume mounts reset to root,
# but the app runs as non-root 'claude' user.
mkdir -p /data/repos
chown -R claude:claude /data

# Drop privileges and exec uvicorn as the claude user
exec gosu claude uvicorn backend.main:app --host 0.0.0.0 --port 8000 "$@"
