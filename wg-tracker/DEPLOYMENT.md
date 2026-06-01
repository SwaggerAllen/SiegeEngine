# Deployment — Digital Ocean App Platform

The application is a single container image whose behavior is selected by the
`ROLE` environment variable, so the same image backs every App Platform
component.

| ROLE       | Command                                  | Use as                         |
|------------|------------------------------------------|--------------------------------|
| `web`      | migrate, then `uvicorn …web.app:app`     | HTTP **service** (UI + health) |
| `pipeline` | migrate, then `wgtracker ingest`         | **scheduled job** (weekly)     |
| `migrate`  | `alembic upgrade head`                   | pre-deploy migration job       |
| `mcp`      | `python -m wgtracker.mcp_server`         | local stdio MCP (usually local)|

## 1. Provision

- Managed PostgreSQL 16 (the spec relies on JSONB, enums, and a generated
  `tsvector` + GIN index for full-text search).
- An App Platform app from this repo. A starter spec is in
  [`.do/app.yaml`](.do/app.yaml).

## 2. Configuration

Non-secret settings live in `config.yaml` (baked into the image). Secrets are
**environment variables**, set as encrypted vars in the App Platform UI:

| Var                 | Notes                                                            |
|---------------------|------------------------------------------------------------------|
| `DATABASE_URL`      | from the managed DB binding (`${wgtracker-db.DATABASE_URL}`)     |
| `ANTHROPIC_API_KEY` | Batch-API summarization/categorization                           |
| `SESSION_SECRET`    | signs web session cookies; `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `PUBLIC_BASE_URL`   | public app URL, used to render absolute invite links (`${APP_URL}`) |
| `CONFIG_PATH`       | defaults to `/app/config.yaml`                                   |
| `LOG_LEVEL`         | `INFO` (structured JSON logs go to stdout)                       |

`postgres://` / `postgresql://` URLs are normalized to the psycopg driver
automatically.

## 3. Migrations

The `web` and `pipeline` roles both run `alembic upgrade head` on startup, so a
fresh deploy is immediately usable. For stricter control, run a dedicated
`ROLE=migrate` pre-deploy job and disable startup migration by deploying the
`migrate` job ahead of the service.

## 4. Health check

`GET /healthz` returns `{"status":"ok","db":true}` when the DB is reachable.
Point the App Platform health check at it (already set in `.do/app.yaml`).

## 5. Scheduled processing

Configure the `pipeline` job to run **weekly** (real-time updates are out of
scope; weekly batch is the design point). It ingests new messages, syncs draft
metadata, and runs the Batch-API summarization/categorization stages.

> **Validate before backfilling.** Run the pipeline on a small sample first
> (`wgtracker ingest --wg mls --since <last-month>`) and have a human spot-check
> a few summaries against their source URLs before turning on the full backfill.
> The budget guard (`processing.budget_usd`, default $200) refuses to dispatch a
> batch that would exceed the budget without `--force`.

## 6. MCP server

The MCP server is normally run **locally** on the user's machine, connecting
directly to the managed Postgres over `DATABASE_URL` (simplest; no auth layer to
serve the MCP protocol). Run it with `ROLE=mcp` only if you specifically need it
reachable remotely.

## Building / running locally

```bash
docker build -f wg-tracker/Dockerfile -t wg-tracker wg-tracker
docker run --rm -e ROLE=migrate -e DATABASE_URL=... wg-tracker
docker run --rm -p 8000:8000 \
  -e ROLE=web -e DATABASE_URL=... -e SESSION_SECRET=... -e PUBLIC_BASE_URL=http://localhost:8000 \
  wg-tracker
```
