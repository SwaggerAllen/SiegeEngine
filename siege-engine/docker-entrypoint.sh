#!/bin/bash
set -e

# Fix /data ownership — Fly.io volume mounts reset to root,
# but the app runs as non-root 'claude' user.
mkdir -p /data/repos
chown -R claude:claude /data

# Restore Claude CLI config from backup if missing
CLAUDE_CONFIG="/home/claude/.claude.json"
CLAUDE_BACKUP_DIR="/home/claude/.claude/backups"
if [ ! -f "$CLAUDE_CONFIG" ] && [ -d "$CLAUDE_BACKUP_DIR" ]; then
    LATEST_BACKUP=$(ls -t "$CLAUDE_BACKUP_DIR"/.claude.json.backup.* 2>/dev/null | head -1)
    if [ -n "$LATEST_BACKUP" ]; then
        echo "Restoring Claude CLI config from backup: $LATEST_BACKUP"
        cp "$LATEST_BACKUP" "$CLAUDE_CONFIG"
        chown claude:claude "$CLAUDE_CONFIG"
    fi
fi

# Drop privileges and exec uvicorn as the claude user.
#
# --proxy-headers + --forwarded-allow-ips='*' make uvicorn trust
# X-Forwarded-Proto from the upstream HTTPS terminator (Cloudflare /
# nginx / Caddy / whatever sits in front of the droplet). Without it,
# any redirect uvicorn emits scheme-downgrades to http:// — which
# silently strips Authorization headers on the client retry, breaking
# the MCP transport. The droplet is single-tenant behind one TLS
# terminator, so trusting any proxy is fine here.
exec gosu claude uvicorn backend.main:app \
    --host 0.0.0.0 --port 8000 \
    --proxy-headers --forwarded-allow-ips='*' \
    "$@"
