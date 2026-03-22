# SiegeEngine

AI-powered project scaffolding pipeline. Generates system architectures, component designs, implementation plans, and code through a multi-stage pipeline with human review gates. Uses the Claude CLI for all generation with web research capabilities, and includes an interactive chat interface for project-level conversations.

## Prerequisites

- Python 3.11+
- Node.js 20+
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) (`npm install -g @anthropic-ai/claude-code`)
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

## Pipeline Stages

The pipeline runs 10 stages, each with optional AI review and human review gates:

1. **System Requirements** — gather and document project requirements
2. **System Architecture** — design the overall system architecture
3. **Component Extraction** — extract components via 3-way consensus voting
4. **Component Architectures** — per-component architecture (fan-out)
5. **Sub-Component Extraction** — extract sub-components per component (fan-out)
6. **Component Plans** — per leaf component implementation plans (fan-out)
7. **Sub-Component Architectures** — per sub-component architecture (fan-out)
8. **Sub-Component Plans** — per sub-component implementation plans (fan-out)
9. **Code Generation** — generate code with full tool access (fan-out per leaf)
10. **Code Review & Fix** — automated code review and fixes (fan-out per leaf)

Document stages (1-8) use the Claude CLI with web research tools. Code stages (9-10) run in the project's git repo with full tool access (bash, file editing, etc.).

## Architecture: Event Sourcing

All pipeline state changes flow through an event-sourced system:
- **Events** (`pipeline/events.py`) — immutable records of state changes (e.g., `STAGE_STARTED`, `HUMAN_APPROVED`)
- **Reducer** (`pipeline/reducer.py`) — pure function that applies events to produce a snapshot
- **Snapshot** (`PipelineSnapshot`) — materialized view that is the **single source of truth** for pipeline state
- DB model status fields (`Artifact.status`, `StageExecution.status`) are projections — written for query convenience but never read for state decisions

## Features

- **Interactive Chat** — project-level chat tab powered by Claude CLI with access to the project's git repo
- **Prompt Editor** — customize system messages, context templates, and model settings per stage
- **AI Review** — configurable AI review generates detailed feedback documents
- **Human Review Gates** — approve, reject with feedback, or edit & approve at each stage
- **DAG Visualization** — interactive pipeline graph with real-time status updates
- **Mobile Responsive** — full touch-friendly mobile layout
- **GitHub Integration** — push branches and open PRs from the UI
- **Fly.io Deployment** — production-ready with Dockerfile and deployment guide

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
  chat/          # Chat WebSocket endpoint + session management
  cli/           # Claude CLI manager + structured data extractor
  config.py      # All settings (env vars with SIEGE_ prefix)
  database.py    # SQLAlchemy + SQLite setup
  dag/           # DAG traversal, staleness propagation
  git_manager/   # Git operations (commit, diff, push)
  github/        # GitHub OAuth + API (PRs, status)
  main.py        # FastAPI app entry point
  models.py      # SQLAlchemy ORM models
  pipeline/      # Pipeline engine, stage execution
    engine.py    # Orchestrator (fan-out, review gates)
    events.py    # Event type constants
    reducer.py   # Pure reducer: events → snapshot state
    event_store.py # Append events, update materialized snapshot
    nodes/       # Generate, AI review, component extraction
    prompts/     # Prompt templates (editable via UI)
    routes.py    # Pipeline API endpoints
  projects/      # Project CRUD
  websocket/     # Real-time pipeline progress

frontend/
  src/
    api/         # Axios client
    components/  # React components (DAG, editor, chat, panels)
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
| `SIEGE_MAX_CONCURRENT_LLM_CALLS` | `5` | Max parallel CLI invocations |
| `SIEGE_CLI_TIMEOUT_DOCUMENT` | `300` | Timeout (seconds) for document generation |
| `SIEGE_CLI_TIMEOUT_CODE` | `900` | Timeout (seconds) for code generation/review |
| `SIEGE_CLI_MAX_BUDGET_CODE` | `5.0` | Max USD per code gen/review invocation |
| `SIEGE_DATABASE_URL` | `sqlite:///data/siege_engine.db` | Database connection string |
| `SIEGE_JWT_EXPIRY_HOURS` | `24` | Token lifetime |
| `SIEGE_GITHUB_CLIENT_ID` | *(empty)* | GitHub OAuth client ID |
| `SIEGE_GITHUB_CLIENT_SECRET` | *(empty)* | GitHub OAuth client secret |
| `SIEGE_CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed CORS origins |

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for Fly.io deployment instructions.

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
