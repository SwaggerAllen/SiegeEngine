# SiegeEngine

SiegeEngine drafts, reviews, and approves a project's architecture
in compressed tiers. It runs as a Claude Code plugin: skills do the
LLM work, an MCP server provides typed reads of project state, and
git holds the artifacts and per-scope state JSON together.

The tier chain is a meaning engine — each pass produces compressed
handles (names, roles, API intents, public surfaces) the next pass
reasons from directly. The chain alternates extraction, rotation,
and compression:

- **feature_expansion** — extraction from the project input doc.
- **requirements** — rotation onto a system-level axis.
- **sysarch** — compression: project-wide architecture sections
  decomposing approved requirements into top-level components.
- **comparch** — last compression before implementation: carves a
  comp into subcomps and per-subcomp `<owns>` claims on parent
  resps + feat slices.
- **subcomparch** — leaf articulation; rich `<public-surface>` etc.
- **impl** — implementation-level detail per leaf.
- **fanin** — bottom-up synthesis from impl + sub pubapis.

Every state transition is exactly one git commit (artifact body +
state JSON together). The MCP server reads from git; skills commit
and push. There is no separate database for project state.

## Components

- **`siege_mcp/`** — read-only MCP server. Per-tier context readers,
  body section + review XML parsers, score histogram aggregation,
  validation gate, writer CLI invoked by skills. Mounted at
  `/siege_mcp` on the main FastAPI app.
- **`.claude-plugin/`** — the Claude Code plugin manifest, 25 skills
  (per-tier draft + review + regen-with-feedback × 7, plus shared
  mark-* and repair-state-drift), 7 per-tier generator subagents
  for fan-out, and 5 slash commands.
- **`backend/`** — the existing FastAPI dashboard (project CRUD,
  auth, GitHub OAuth, git_manager). The pre-migration
  SQLAlchemy + job-queue stack lives here too and is slated for
  deletion in Phase 4 — see `docs/migration/deletion-inventory.md`.
- **`frontend/`** — React + Vite dashboard. Reads project state
  from the MCP server, renders structure + reviews + scores.
  Branch selector at the top switches the ref every read is taken
  against.

## Slash commands

Once the plugin is installed (or the `.claude/` content seeded into
the project repo via the bootstrap script):

- `/scaffold` — bootstrap the upstream chain (features →
  requirements → sysarch).
- `/run_tier <tier>` — draft + review every absent/drafted scope
  at a tier, topologically.
- `/regen_below <tier> <threshold>` — regenerate scopes below a
  review score, threading the prior review as feedback.
- `/continue <batch_id>` — resume an interrupted batch (fills
  gaps; doesn't redo completed work).
- `/status` — per-tier snapshot: counts, score histogram, worst-N.

Full reference (workflows, skill catalog, dashboard pages, gotchas)
lives at `frontend/src/content/cheatsheet.md` and is served
in-browser at `https://siege.strutco.io/cheatsheet`.

## Setup (development)

### Prerequisites

- Python 3.11+
- Node.js 20+
- An [Anthropic API key](https://console.anthropic.com/) (the
  dashboard backend still uses it for the legacy generation paths
  during the migration; new work runs through Claude Code, which
  uses its own login).

### Local dev

```bash
cp .env.example .env
# set SIEGE_ANTHROPIC_API_KEY + SIEGE_JWT_SECRET_KEY
# (e.g. `openssl rand -hex 32` for the JWT secret)

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

uvicorn backend.main:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev    # localhost:5173, proxies to :8000
```

First user to register is the admin. Subsequent users need an
invite link from the admin dashboard.

### Plugin install

**Desktop Claude Code**:

```text
/plugin install swaggerallen/siegeengine
```

Persists to your CC user config — install once per device.

**Mobile Claude Code** (`/plugin install` is unsupported there):
from inside the project repo you want to drive,

```bash
curl -fsSL https://siege.strutco.io/bootstrap.sh | bash
```

Writes `.mcp.json` + mirrors `.claude/commands/`, `.claude/skills/`,
`.claude/agents/` into the repo. Commit + push the result; mobile
CC auto-discovers the contents on the next open. Then:

```bash
export SIEGE_TOKEN=<your JWT from siege.strutco.io/cheatsheet>
```

The `.mcp.json` references `${SIEGE_TOKEN}` so the MCP client
substitutes it at request time.

## Verification

Run from `siege-engine/` before declaring a change complete:

```bash
# Backend
.venv/bin/python -m pytest tests/v2/ siege_mcp/tests/ -q
ruff check backend/ siege_mcp/ tests/
ruff format --check backend/ siege_mcp/ tests/
rm -rf .mypy_cache && mypy backend/ siege_mcp/

# Frontend (from siege-engine/frontend/)
npx tsc -b --noEmit --force
npx vitest run
npm run lint
npx vite build
```

Always nuke `.mypy_cache` first — stale cache has masked real type
errors more than once.

## Project layout

```
.claude-plugin/        # Plugin manifest, skills, commands, agents
LICENSE                # AGPL-3.0-or-later (canonical text)
siege-engine/
  backend/             # FastAPI dashboard (auth, projects, git_manager)
  siege_mcp/           # Read-only MCP server
    cli.py             # Writer CLI invoked by skills
    git_view.py        # Per-(project, ref, sha) snapshot substrate
    server.py          # FastAPI app with /api/* + /mcp transports
    tiers/             # Per-tier generation + review context readers
    prompts/           # Per-tier instruction text (extracted from old backend)
    parsers/           # body sections + review XML
  frontend/            # React + Vite dashboard
    src/content/cheatsheet.md   # User-facing reference (load-bearing)
  scripts/
    siege-bootstrap.sh # Mobile-CC on-ramp: seeds .claude/ + .mcp.json
  docs/migration/      # Schema + MCP surface + deletion inventory + status
  Dockerfile           # Single image; CD scps + builds on the DO droplet
  DEPLOYMENT.md        # Full deployment guide
```

## Configuration reference

All env vars use the `SIEGE_` prefix. See `backend/config.py` for
the full list and defaults.

| Variable | Default | Description |
|---|---|---|
| `SIEGE_ANTHROPIC_API_KEY` | *(required)* | Anthropic API key for legacy backend |
| `SIEGE_JWT_SECRET_KEY` | *(required, change me)* | JWT signing secret |
| `SIEGE_JWT_EXPIRY_HOURS` | `720` (30 days) | Token lifetime |
| `SIEGE_DATABASE_URL` | `sqlite:///data/siege_engine.db` | DB connection (legacy backend) |
| `SIEGE_GIT_REPOS_BASE_PATH` | `data/repos` | Per-project clone cache root |
| `SIEGE_DEFAULT_MODEL` | `claude-opus-4-6` | LLM model (legacy backend only) |
| `SIEGE_CLI_TIMEOUT` | `1800` | Per-CLI-invocation timeout (legacy) |
| `SIEGE_MAX_CONCURRENT_LLM_CALLS` | `1` | Max parallel CLI invocations |
| `SIEGE_CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed CORS origins |
| `SIEGE_GITHUB_CLIENT_ID` | *(empty)* | GitHub OAuth client ID |
| `SIEGE_GITHUB_CLIENT_SECRET` | *(empty)* | GitHub OAuth secret |

## Deployment

DigitalOcean droplet, single docker container, deploy via ssh +
docker on push to `main`. See [DEPLOYMENT.md](DEPLOYMENT.md) for
the full guide (droplet provisioning, secrets, TLS, volumes).

## License

SiegeEngine is licensed under the [GNU Affero General Public
License v3.0 or later](../LICENSE) (AGPL-3.0-or-later).

If you run a modified version on a server that interacts with users
over a network, you must make the source code of your version
available to those users (AGPL §13). The hosted instance at
`siege.strutco.io` complies via the "Source" link in the dashboard
footer pointing back at this repository.

## Documentation index

- [docs/migration/status.md](docs/migration/status.md) — current
  migration phase, what's landed, what's pending.
- [docs/migration/state-schema.md](docs/migration/state-schema.md) —
  state JSON schema v1, path layout, batches, idempotency.
- [docs/migration/mcp-surface.md](docs/migration/mcp-surface.md) —
  MCP tool surface (list_refs, get_state, list_tier,
  get_generation_context, …).
- [docs/migration/deletion-inventory.md](docs/migration/deletion-inventory.md)
  — Phase 4 deletion punch list (~30K LOC slated to go).
- [DEPLOYMENT.md](DEPLOYMENT.md) — DigitalOcean deploy guide.
- [frontend/src/content/cheatsheet.md](frontend/src/content/cheatsheet.md)
  — user-facing workflow + slash command reference.
- [CLAUDE.md](CLAUDE.md) — Claude Code session notes (verification
  commands, working patterns, load-bearing invariants).
