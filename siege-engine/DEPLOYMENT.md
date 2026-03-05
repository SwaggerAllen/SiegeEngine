# Deploying SiegeEngine to Fly.io

## Prerequisites

1. Install [flyctl](https://fly.io/docs/hands-on/install-flyctl/)
2. Create a [Fly.io account](https://fly.io) and log in: `fly auth login`
3. An Anthropic API key for Claude

## Initial Setup

### 1. Create the Fly app

```bash
cd siege-engine
fly launch --no-deploy
```

When prompted, accept the defaults or customize the app name and region.

### 2. Create a persistent volume

SQLite needs persistent storage. Create a volume in the same region as your app:

```bash
fly volumes create siege_data --size 10 --region iad
```

### 3. Set secrets

```bash
fly secrets set \
  SIEGE_ANTHROPIC_API_KEY=sk-ant-... \
  SIEGE_JWT_SECRET_KEY=$(openssl rand -hex 32)
```

Optional secrets:
```bash
fly secrets set \
  SIEGE_GITHUB_CLIENT_ID=your_github_client_id \
  SIEGE_GITHUB_CLIENT_SECRET=your_github_client_secret
```

### 4. Deploy

```bash
fly deploy
```

## Post-Deploy

### Verify

```bash
fly status
fly logs
```

Visit `https://your-app-name.fly.dev` to access the app.

### SSH Access

```bash
fly ssh console
```

### View Database

```bash
fly ssh console -C "sqlite3 /data/siege_engine.db '.tables'"
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SIEGE_ANTHROPIC_API_KEY` | Anthropic API key (set as secret) | Required |
| `SIEGE_JWT_SECRET_KEY` | JWT signing key (set as secret) | Required |
| `SIEGE_DATABASE_URL` | SQLite database path | `sqlite:////data/siege_engine.db` |
| `SIEGE_GIT_REPOS_BASE_PATH` | Git repos directory | `/data/repos` |
| `SIEGE_CORS_ORIGINS` | Allowed CORS origins (JSON array) | `["https://siege-engine.fly.dev"]` |
| `SIEGE_DEFAULT_MODEL` | Default Claude model | `claude-sonnet-4-20250514` |
| `SIEGE_GITHUB_CLIENT_ID` | GitHub OAuth client ID | Optional |
| `SIEGE_GITHUB_CLIENT_SECRET` | GitHub OAuth client secret | Optional |

### Custom Domain

```bash
fly certs add your-domain.com
```

Then add a CNAME record pointing `your-domain.com` to `your-app-name.fly.dev`.

Update CORS origins after adding a custom domain:
```bash
fly secrets set SIEGE_CORS_ORIGINS='["https://your-domain.com"]'
```

## Scaling Notes

- **Single instance only**: SQLite requires a single writer, so do not scale beyond 1 machine.
- **Volume is region-locked**: The persistent volume is tied to the region where it was created.
- **Always-on**: Auto-stop is disabled to prevent killing in-progress pipeline stages. The machine runs continuously.

## Updating

To deploy a new version:

```bash
fly deploy
```

The volume data (database, git repos) persists across deploys.
