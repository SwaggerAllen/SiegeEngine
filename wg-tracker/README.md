# IETF Working Group Activity Tracker

A tool for tracking IETF working-group consensus and activity on specific topics
over time (MLS, MIMI, CFRG to start). It is **not** a vector/RAG tool: it's a
structured archive of per-thread LLM summaries stored in PostgreSQL, organized by
date and categorized against a configurable topic taxonomy, where **every summary
links back to its source thread in the IETF archive for one-click verification.**

## Why this design

The need is "show me organized history of topic X" and "what's happened recently
in topic X", not "find content semantically similar to my query". Structured
queries against summarized threads serve those directly, keep every claim
verifiable via a source URL, keep LLM work bounded (one thread = one summary),
and match the append-only, thread-structured shape of mailing-list archives.

## What's here

```
wgtracker/
  config.py          load config.yaml + env secrets
  models.py          SQLAlchemy models (Postgres: JSONB, enums, FKs, FTS)
  db.py              engine/session helpers
  ingestion/         Stage 1: fetch mbox, parse RFC 5322, reconstruct threads
  processing/        Stage 2/3: clean quotes+sigs, extract drafts, datatracker sync
  llm/               Stage 2/4/5: Batch-API prefilter, summarize, categorize
  pipeline.py        orchestrates all stages, idempotent, budget-guarded
  queries.py         shared query layer (CLI + MCP + web all use this)
  cli.py             Typer CLI (Stage 6)
  mcp_server.py      MCP server exposing the queries to Claude
  web/               authenticated browse UI (addendum)
alembic/             migrations
config.yaml          working groups, topics, models, thresholds (non-secret)
Dockerfile           multi-stage container build
```

## Pipeline stages

1. **Ingestion** — fetch the per-list mbox export from `mailarchive.ietf.org`,
   parse RFC 5322 headers, dedupe by `Message-ID`, reconstruct threads from
   `References`/`In-Reply-To` (with a subject + time-proximity fallback for broken
   chains).
2. **Pre-processing** — strip quoted text and signature blocks; flag
   administrative/contentless messages with Haiku; extract `draft-*` / `RFC NNNN`
   references.
3. **Draft sync** — fetch draft metadata from the IETF Datatracker, refresh
   when stale, link threads ↔ drafts (with the specific versions discussed).
4. **Summarization** — Sonnet 4.6 via the **Batch API**, one bounded summary per
   thread, grounded in referenced-draft metadata. Distinguishes *what was said*
   from *what the WG concluded* via the `consensus_state` field.
5. **Categorization** — Haiku via the Batch API against the configured taxonomy
   (cheap; re-run on taxonomy changes without re-summarizing).
6. **Query interface** — CLI + MCP server, both returning source URLs.

All LLM work uses the Batch API (50% discount) and is logged with token counts
and estimated cost; a budget guard refuses to exceed `processing.budget_usd`.

## Quick start (local)

```bash
# 1. Postgres + env
cp .env.example .env            # set DATABASE_URL, ANTHROPIC_API_KEY, SESSION_SECRET
export $(grep -v '^#' .env | xargs)

# 2. install + migrate
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
alembic upgrade head

# 3. seed taxonomy, then validate on a small sample BEFORE backfilling
wgtracker seed-topics
wgtracker ingest --wg mls --since 2025-05-01     # one month of MLS
wgtracker list-threads --wg mls
wgtracker show-thread <thread_id>                # spot-check vs the source URL

# 4. once spot-checks look right, backfill all configured WGs
wgtracker ingest
wgtracker costs                                  # watch the budget
```

### CLI

```
wgtracker list-threads --topic federation --since 2025-10-01
wgtracker show-thread <thread_id>
wgtracker recent --topic federation
wgtracker participants --topic federation
wgtracker drafts --topic federation
wgtracker draft draft-ietf-mls-extensions
wgtracker search "history sharing"
wgtracker recategorize        # after editing the taxonomy in config.yaml
wgtracker costs               # spend by stage vs budget
```

### MCP server

```bash
python -m wgtracker.mcp_server     # stdio; connects to DATABASE_URL
```

Tools: `search_threads`, `get_thread_detail`, `recent_activity`,
`topic_overview`, `list_drafts`, `get_draft`, `draft_discussion_history`. Every
tool returns the source `archive_url` alongside summaries so Claude can cite them.

Register with Claude Desktop / Claude Code (local, talking to the remote Postgres):

```json
{
  "mcpServers": {
    "wg-tracker": {
      "command": "python",
      "args": ["-m", "wgtracker.mcp_server"],
      "env": { "DATABASE_URL": "postgres://...", "CONFIG_PATH": "/path/config.yaml" }
    }
  }
}
```

## Web UI (authenticated — spec addendum)

A minimal server-rendered browse UI:

```bash
uvicorn wgtracker.web.app:app --host 0.0.0.0 --port 8000
```

- **First registrant becomes the admin** (visit `/setup` on a fresh database).
- The admin mints **single-use, read-only invite links** at `/admin`; recipients
  set their own email/password at `/invite/<token>` and get a **viewer** account.
- All archive views (threads, drafts, topics, full-text search) require login;
  invite management is admin-only.
- `/healthz` is the App Platform health check.

Set `SESSION_SECRET` (cookie signing) and `PUBLIC_BASE_URL` (used to render
absolute invite links).

## Deployment (Digital Ocean App Platform)

See [DEPLOYMENT.md](DEPLOYMENT.md). The image is built multi-stage, runs Alembic
migrations on startup, logs structured JSON to stdout, and supports three roles
via `docker-entrypoint.sh`: `web` (the UI + health check), `pipeline` (the
scheduled ingestion/processing job), and `migrate`.

## Cost expectations

Backfilling one year of MLS+MIMI+CFRG is estimated at **$20–50**; ongoing is
**~$15/year**. The pipeline tracks spend per stage and will not exceed
`processing.budget_usd` (default $200) without `--force`.

Licensed under AGPL-3.0-or-later.
