# Deploying SiegeEngine to DigitalOcean

SiegeEngine runs as a single Docker container on a DigitalOcean droplet.
Deployment is automated by `.github/workflows/deploy.yml`: every push to
`main` SCPs the repo to the droplet, builds the image there, and restarts
the container. SQLite data and the Claude CLI's login state live in named
docker volumes that survive deploys.

## Architecture at a glance

- **Compute**: a single DigitalOcean droplet (any region). Docker installed.
- **Process**: one container, port 80 → container's port 8000.
- **Storage**: two named docker volumes
  - `siege_data` → `/data` (SQLite DB + cloned git repos)
  - `claude_config` → `/home/claude/.claude` (Claude CLI login state)
- **TLS**: terminated upstream (the deploy currently uses
  `https://siege.strutco.io` via a CNAME → droplet IP). If you don't have
  a TLS terminator yet, put the droplet behind Cloudflare or run nginx +
  certbot on the host. The container itself speaks plain HTTP on :8000.
- **Single instance only**: SQLite has one writer. Do not horizontally
  scale this app.

## Initial droplet setup (one-time)

These steps prepare a fresh droplet to receive automated deploys.

### 1. Create the droplet

A 2 GB / 1 vCPU droplet is enough to start. Pick the Docker marketplace
image so docker is preinstalled, or install it manually:

```bash
ssh root@<droplet-ip>
curl -fsSL https://get.docker.com | sh
```

### 2. Create the deploy user

The GitHub Actions workflow logs in as `deploy`. Create the user, give it
docker access, and authorize an SSH key:

```bash
adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy
mkdir -p /home/deploy/.ssh
# paste the deploy public key (matches DROPLET_SSH_KEY secret)
nano /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

Generate the keypair locally if you don't already have one:

```bash
ssh-keygen -t ed25519 -f siege-deploy-key -C "siege-deploy"
# public  key → /home/deploy/.ssh/authorized_keys on the droplet
# private key → DROPLET_SSH_KEY GitHub secret
```

### 3. Pre-create the docker volumes

Both volumes need to exist before the first deploy so the container has
somewhere to mount:

```bash
sudo -u deploy docker volume create siege_data
sudo -u deploy docker volume create claude_config
```

### 4. Log into the Claude CLI

The container shells out to the `claude` CLI for LLM calls and uses login
credentials, not an API key. Bootstrap the login by running an interactive
container against the persistent volume once:

```bash
sudo -u deploy docker run -it --rm \
  -v claude_config:/home/claude/.claude \
  --entrypoint /bin/bash \
  siege-engine:latest \
  -c "claude login"
```

(You can run this only after the first deploy has built the image. On a
totally fresh droplet, deploy once first — the app will start but CLI calls
will fail until you complete the login.)

## GitHub repository secrets

Set these under **Settings → Secrets and variables → Actions** in the
GitHub repo. The deploy workflow reads them.

| Secret | Description |
|---|---|
| `DROPLET_IP` | Droplet's public IPv4 |
| `DROPLET_SSH_KEY` | Private key for the `deploy` user (full PEM, including BEGIN/END lines) |
| `SIEGE_ANTHROPIC_API_KEY` | Anthropic API key. The server keeps it set for completeness, but the Claude CLI uses its own login state. |
| `SIEGE_JWT_SECRET_KEY` | JWT signing secret. Generate with `openssl rand -hex 32`. Rotating this invalidates all existing sessions. |

## Runtime configuration

`backend/config.py` defines the settings, all of which are also overridable
via environment variables prefixed with `SIEGE_`. The deploy workflow sets
these on the container directly:

| Variable | Value (in deploy.yml) |
|---|---|
| `SIEGE_DATABASE_URL` | `sqlite:////data/siege_engine.db` |
| `SIEGE_GIT_REPOS_BASE_PATH` | `/data/repos` |
| `SIEGE_CORS_ORIGINS` | JSON list — currently the droplet IP and `siege.strutco.io` |
| `SIEGE_ANTHROPIC_API_KEY` | from GitHub secret |
| `SIEGE_JWT_SECRET_KEY` | from GitHub secret |

To change CORS origins, custom domain, or any other setting, edit
`.github/workflows/deploy.yml` and push.

## Database migrations

Migrations run automatically inside the container at startup. The boot
sequence (in `backend/database.py`) is:

1. Enable SQLite WAL mode and a 30s busy timeout.
2. Read the current revision from `alembic_version`.
3. If the table is empty *and* `projects` already exists (i.e. a previously
   running instance), stamp at the base revision and upgrade to head.
4. If the table is empty and `projects` does not exist, run all migrations
   from scratch.
5. Otherwise, upgrade from the current revision to head.
6. Run `Base.metadata.create_all` as a safety net for any tables alembic
   missed.

This means *fresh deploys to a new droplet just work*. Existing droplets
upgrade automatically on container restart as long as the current revision
in the DB matches a known migration in the repo.

### One-off: deploying the v2 squash

A single squashed migration (`v2_initial_schema`) replaced the historical
v1 chain. If a droplet's `alembic_version` row still points at a migration
ID that no longer exists in the repo (e.g. the v1 gut migration), the boot
will crash with `KeyError`. The fix is to clear the row so the bootstrap
takes the "stamp existing schema" branch:

```bash
docker exec -it siege-engine python -c \
  "import sqlite3; c = sqlite3.connect('/data/siege_engine.db'); c.execute('DELETE FROM alembic_version'); c.commit()"
```

Then redeploy or restart the container. This is a one-off; it does not need
to be re-run after the boot succeeds once.

## Manual deploy (bypassing CI)

If you ever need to deploy without going through GitHub Actions, the
workflow steps reduce to:

```bash
# from your dev machine
rsync -avz --exclude='.git' --exclude='node_modules' --exclude='dist' \
  siege-engine/ deploy@<droplet-ip>:/tmp/siege-deploy/siege-engine/

# on the droplet
ssh deploy@<droplet-ip>
cd /tmp/siege-deploy/siege-engine
docker build -t siege-engine:latest .
docker stop siege-engine || true
docker rm siege-engine || true
docker run -d \
  --name siege-engine \
  --restart=unless-stopped \
  --log-driver json-file \
  --log-opt max-size=50m \
  --log-opt max-file=5 \
  -p 80:8000 \
  -v siege_data:/data \
  -v claude_config:/home/claude/.claude \
  -e SIEGE_ANTHROPIC_API_KEY=... \
  -e SIEGE_JWT_SECRET_KEY=... \
  -e SIEGE_CORS_ORIGINS='["https://siege.strutco.io"]' \
  -e SIEGE_DATABASE_URL=sqlite:////data/siege_engine.db \
  -e SIEGE_GIT_REPOS_BASE_PATH=/data/repos \
  siege-engine:latest
```

## Operations

### Tail logs

```bash
ssh deploy@<droplet-ip> docker logs -f siege-engine
```

### Inspect the database

The container ships without the `sqlite3` CLI binary, so use Python:

```bash
ssh deploy@<droplet-ip> docker exec -it siege-engine python -c \
  "import sqlite3; c=sqlite3.connect('/data/siege_engine.db'); print(c.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall())"
```

### Back up the data volume

```bash
ssh deploy@<droplet-ip> \
  "docker run --rm -v siege_data:/data -v /tmp:/backup alpine \
    tar czf /backup/siege_data_$(date +%Y%m%d).tar.gz -C /data ."
scp deploy@<droplet-ip>:/tmp/siege_data_*.tar.gz ./
```

### Restart without redeploying

```bash
ssh deploy@<droplet-ip> docker restart siege-engine
```

## Health check

The container exposes `GET /healthz` on port 8000. From the droplet:

```bash
curl http://localhost:80/healthz
```

A successful response means migrations have completed and the app is
serving requests.
