# SiegeEngine

AI-powered project scaffolding pipeline. Generates system architectures, component designs, implementation plans, and code through a multi-stage pipeline with human review gates.

## Prerequisites

- Python 3.11+
- Node.js 18+
- An [Anthropic API key](https://console.anthropic.com/)

## Setup

### 1. Environment

```bash
cp .env.example .env
```

Edit `.env` and set:
- `SIEGE_ANTHROPIC_API_KEY` — your Anthropic API key
- `SIEGE_JWT_SECRET_KEY` — a random string for JWT signing (e.g. `openssl rand -hex 32`)

### 2. Backend

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -e ".[dev]"

# Start the server
uvicorn backend.main:app --reload --port 8000
```

The database (SQLite) is created automatically on first run at `data/siege_engine.db`.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:5173` and proxies API calls to the backend.

### 4. First User

Open `http://localhost:5173` and register. The first user is automatically an admin. Subsequent users require an invite link (generated from the admin's dashboard).

## GitHub Integration (Optional)

To enable pushing branches and opening PRs from the UI:

1. [Create a GitHub OAuth App](https://github.com/settings/developers)
   - Homepage URL: `http://localhost:5173`
   - Callback URL: `http://localhost:5173/github/callback`
2. Set in `.env`:
   ```
   SIEGE_GITHUB_CLIENT_ID=your-client-id
   SIEGE_GITHUB_CLIENT_SECRET=your-client-secret
   ```
3. In the project dashboard, go to **Settings** > **Connect GitHub**

## Project Structure

```
backend/
  auth/          # JWT auth, registration, invite links
  config.py      # All settings (env vars with SIEGE_ prefix)
  database.py    # SQLAlchemy + SQLite setup
  dag/           # DAG traversal, staleness propagation
  git_manager/   # Git operations (commit, diff, push)
  github/        # GitHub OAuth + API (PRs, status)
  main.py        # FastAPI app entry point
  models.py      # SQLAlchemy ORM models
  pipeline/      # Pipeline engine, stage execution
    engine.py    # Orchestrator (fan-out, review gates)
    nodes/       # Generate, AI review, component extraction
    prompts/     # Prompt templates (editable via UI)
    routes.py    # Pipeline API endpoints
  projects/      # Project CRUD
  websocket/     # Real-time pipeline progress

frontend/
  src/
    api/         # Axios client
    components/  # React components (DAG, editor, panels)
    hooks/       # WebSocket hook
    pages/       # Login, project list, dashboard
    store/       # Zustand stores
    types/       # TypeScript interfaces
```

## Configuration Reference

All settings use the `SIEGE_` env prefix. See `backend/config.py` for defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `SIEGE_ANTHROPIC_API_KEY` | *(required)* | Anthropic API key |
| `SIEGE_JWT_SECRET_KEY` | *(required)* | JWT signing secret |
| `SIEGE_DEFAULT_MODEL` | `claude-sonnet-4-20250514` | Default LLM model |
| `SIEGE_DEFAULT_TEMPERATURE` | `0.3` | Default LLM temperature |
| `SIEGE_MAX_CONCURRENT_LLM_CALLS` | `5` | Max parallel LLM requests |
| `SIEGE_LLM_RETRY_MAX_ATTEMPTS` | `3` | Retries on rate limit |
| `SIEGE_LLM_RETRY_BASE_DELAY` | `1.0` | Base delay (seconds) for retry backoff |
| `SIEGE_DATABASE_URL` | `sqlite:///data/siege_engine.db` | Database connection string |
| `SIEGE_JWT_EXPIRY_HOURS` | `24` | Token lifetime |
| `SIEGE_GITHUB_CLIENT_ID` | *(empty)* | GitHub OAuth client ID |
| `SIEGE_GITHUB_CLIENT_SECRET` | *(empty)* | GitHub OAuth client secret |
| `SIEGE_CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed CORS origins |

## Development

```bash
# Run backend with auto-reload
uvicorn backend.main:app --reload --port 8000

# Run frontend dev server
cd frontend && npm run dev

# Run tests
pytest

# Build frontend for production
cd frontend && npm run build
```

When the frontend is built (`frontend/dist/`), the backend serves it as static files automatically.
