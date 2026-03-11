# Forgewright: Distributed B2B Specification & Implementation Engine

## Vision

Forgewright is an Elixir/Phoenix-based platform that automates the full lifecycle of software specification and implementation for B2B teams. It is architecturally similar to Siege Engine (a Python/React pipeline that generates requirements, architecture, plans, and code through AI-orchestrated stages with human review checkpoints) but is designed from the ground up to operate at enterprise scale: multi-tenant, concurrent pipelines, real-time collaboration, durable execution, and API-first extensibility.

Where Siege Engine runs a single pipeline for a single user with SQLite persistence, Forgewright runs hundreds of concurrent pipelines across organizations, leverages OTP supervision trees for fault tolerance, uses PostgreSQL for multi-tenant data, and exposes a first-class REST/GraphQL API so that CI/CD systems, project management tools, and custom integrations can drive specification and implementation workflows programmatically.

## Core Concept

A **Forge** is a project workspace owned by an **Organization**. Within a Forge, users define a high-level product description (the "seed document"), and Forgewright's pipeline decomposes it through a configurable directed acyclic graph (DAG) of AI-powered stages:

1. **Seed Document** (user-authored product description)
2. **System Requirements** (functional, non-functional, constraints)
3. **System Architecture** (high-level technical design, technology choices)
4. **High-Level Implementation Plan** (epics, milestones, phasing)
5. **Component Map Extraction** (identify top-level modules/services)
6. **Per-Component Requirements** (fan-out: one per component)
7. **Per-Component Architecture** (fan-out: detailed design per component)
8. **Per-Component Implementation Plan** (fan-out: task breakdown per component)
9. **Sub-Component Map Extraction** (fan-out: decompose each component further)
10. **Per-Sub-Component Requirements/Architecture/Plan** (nested fan-out)
11. **Code Generation** (produce source files per leaf component)
12. **Code Review** (AI review of generated code, style/correctness/security)

Each stage produces one or more **Artifacts** (markdown documents or source code files). Artifacts flow through an **AI Review** step (automated quality gate) and optionally a **Human Review** step (approve, reject with feedback, or edit inline). Rejected artifacts are automatically regenerated incorporating the feedback. Approved artifacts become inputs to downstream stages.

The pipeline supports **configurable execution modes** per run:
- **Human review toggle** — enable/disable human approval checkpoints
- **AI self-improvement loops** — how many generate-review-regenerate cycles to run before presenting to a human (0 = no AI review, 1 = single pass, 2+ = iterative refinement)
- **Pause points** — where to pause for human intervention: after every node, before code generation, at fan-out points, or after each requirements-architecture-plan triplet

At the end of each pipeline run, the system creates a **checkpoint**: a Git commit containing all generated artifacts plus a JSON manifest (`forge-state.json`) capturing the complete project state. Users can browse historical runs, compare artifacts across runs, and roll back to any checkpoint.

## Why Elixir

- **OTP Supervision Trees** — Each pipeline run is a supervised process tree. If a stage crashes (LLM timeout, rate limit, parsing error), the supervisor restarts just that stage with exponential backoff, without affecting other concurrent runs.
- **GenServer per Pipeline Run** — Each active run is a GenServer holding its execution state in memory. This enables sub-second stage transitions, real-time progress broadcasting via Phoenix PubSub, and clean process isolation between runs.
- **Phoenix Channels** — Real-time WebSocket communication for live pipeline progress, artifact updates, and collaborative review. Phoenix Channels scale to hundreds of thousands of concurrent connections.
- **Ecto + PostgreSQL** — Multi-tenant data model with row-level security, advisory locks for pipeline coordination, and JSONB columns for flexible artifact metadata.
- **Broadway / GenStage** — For high-throughput fan-out stages (e.g., generating 50 component plans concurrently), Broadway provides back-pressure-aware concurrent processing with configurable concurrency limits per LLM provider.
- **Oban** — Durable job processing for pipeline stages. Jobs survive node restarts, support priority queues, rate limiting, and dead-letter handling. Each stage execution is an Oban job.
- **Distributed Erlang** — Horizontal scaling across multiple nodes. Pipeline runs can be distributed across a cluster, with Horde or pg-based process registries for global process discovery.
- **LiveView** — Server-rendered reactive UI for the dashboard, artifact editor, and review interface. Eliminates the need for a separate SPA build pipeline while still delivering real-time interactivity.

## Multi-Tenancy & Access Control

### Organizations
- Each Organization has a name, billing plan, and member list
- Organizations own Forges (projects)
- Billing is per-organization (seat-based + usage-based for LLM tokens)

### Roles
- **Owner** — Full control. Manage billing, members, integrations.
- **Admin** — Manage Forges, configure pipelines, invite members.
- **Engineer** — Run pipelines, review artifacts, edit documents.
- **Viewer** — Read-only access to Forges and artifacts.

### API Keys
- Organizations can create scoped API keys for CI/CD integration
- Keys have configurable permissions (read-only, run pipelines, admin)
- Keys are rotatable with grace periods

### SSO / SAML
- Enterprise plans support SAML 2.0 SSO
- JIT provisioning of users from identity providers
- Enforce SSO-only login per organization

## Pipeline Configuration

Each Forge has a pipeline configuration that defines:

### Stage Definitions
- **stage_key** — Unique identifier (e.g., `system_requirements`, `component_architecture`)
- **display_name** — Human-readable label
- **order_index** — Execution order within the DAG
- **input_stage_keys** — Which upstream stages provide input artifacts
- **output_artifact_type** — What kind of artifact this stage produces
- **fan_out_strategy** — `none`, `component`, `sub_component`, or `leaf`
- **fan_out_source_field** — Which upstream artifact's field defines the fan-out entities
- **ai_review_enabled** — Whether AI review runs after generation
- **human_review_enabled** — Whether human review is required
- **concurrency_limit** — Max parallel executions for fan-out (default: 10)

### Prompt Configuration
Each stage has customizable prompt templates:
- **system_message** — Sets the AI's role and constraints
- **context_template** — Jinja2-style template that assembles upstream artifacts into the prompt context
- **output_format_instructions** — Specifies the expected output structure (markdown headers, JSON schema, code conventions)
- **revision_instructions** — Template for regeneration prompts when an artifact is rejected
- **model** — LLM model override (default: Claude Sonnet)
- **temperature** — Sampling temperature override
- **max_tokens** — Output token limit

### AI Review Configuration
- Global AI review prompt (shared across stages)
- Per-stage review criteria overrides
- Configurable scoring rubric (1-10 scale with pass threshold)
- Auto-approve threshold (artifacts scoring above this skip human review)

## Artifact Model

```
Artifact:
  id: UUID
  forge_id: UUID (FK -> forges)
  artifact_type: enum (seed_doc, system_requirements, system_architecture, ...)
  name: string
  component_key: string? (null for non-fan-out stages)
  content: text (markdown or source code)
  status: enum (pending, generating, ai_reviewing, awaiting_review, approved, rejected, stale)
  version: integer (incremented on each regeneration)
  file_path: string? (relative path within the Git repo)
  language: string? (programming language for code artifacts)
  ai_review_score: float? (0-10)
  ai_review_feedback: jsonb?
  human_review_notes: text?
  git_commit_sha: string(40)?
  metadata: jsonb (flexible key-value store for stage-specific data)
  created_at: datetime
  updated_at: datetime
```

## Pipeline Run Model

Each time a user starts the pipeline, a PipelineRun record is created:

```
PipelineRun:
  id: UUID
  forge_id: UUID (FK -> forges)
  run_number: integer (sequential per-forge, computed as MAX+1)
  started_by: UUID (FK -> users)
  status: enum (running, paused, completed, failed, cancelled)
  config: jsonb (snapshot of run options: human_review, ai_loops, stop_point)
  git_commit_sha: string(40)? (checkpoint commit at completion)
  started_at: datetime
  completed_at: datetime?
```

## Git Integration

Every Forge is backed by a Git repository:

- **Initialization** — When a Forge is created, a bare Git repo is initialized in the configured storage path.
- **Artifact Commits** — Each artifact generation/update creates an atomic commit with a descriptive message.
- **Checkpoint Commits** — At the end of each pipeline run, a checkpoint commit is created containing `forge-state.json` (full project state manifest) plus any uncommitted changes.
- **Remote Push** — Forges can be configured with a remote Git URL. When auto-push is enabled, checkpoint commits are automatically pushed after each completed run.
- **Historical Browsing** — Users can select any completed run from a dropdown and view the artifacts as they existed at that checkpoint.
- **Branch Strategy** — Each Forge operates on a single branch (default: `main`). The checkpoint commit always goes to the tip of this branch.

## Real-Time Communication

Phoenix Channels provide real-time updates:

### Channel Topics
- `forge:{forge_id}` — Pipeline progress, artifact updates, review notifications
- `org:{org_id}` — Organization-wide notifications (new forges, member changes)
- `user:{user_id}` — Personal notifications (review assignments, mentions)

### Event Types
- `stage_started` — A pipeline stage has begun execution
- `stage_progress` — Streaming LLM output (token-by-token artifact generation)
- `stage_completed` — A stage finished successfully
- `stage_failed` — A stage encountered an error
- `artifact_updated` — An artifact's content or status changed
- `pipeline_paused` — Pipeline is waiting for human review
- `pipeline_completed` — All stages finished; checkpoint committed
- `review_requested` — A specific user has been assigned to review an artifact

## API Design

### REST API (v1)

All endpoints are scoped under `/api/v1` and require Bearer token authentication.

**Organizations**
- `POST /orgs` — Create organization
- `GET /orgs/:org_id` — Get organization details
- `PATCH /orgs/:org_id` — Update organization
- `POST /orgs/:org_id/members` — Invite member
- `DELETE /orgs/:org_id/members/:user_id` — Remove member
- `POST /orgs/:org_id/api-keys` — Create API key

**Forges**
- `POST /orgs/:org_id/forges` — Create forge (with seed document)
- `GET /orgs/:org_id/forges` — List forges
- `GET /forges/:forge_id` — Get forge details
- `PATCH /forges/:forge_id` — Update forge settings
- `DELETE /forges/:forge_id` — Archive forge

**Pipeline**
- `POST /forges/:forge_id/runs` — Start a pipeline run (body: human_review, ai_loops, stop_point)
- `GET /forges/:forge_id/runs` — List pipeline runs
- `GET /forges/:forge_id/runs/:run_number` — Get run details
- `GET /forges/:forge_id/runs/:run_number/state` — Get checkpoint state (forge-state.json)
- `POST /forges/:forge_id/runs/:run_number/cancel` — Cancel a running pipeline
- `POST /forges/:forge_id/stages/:execution_id/review` — Submit review (approve/reject with notes)
- `GET /forges/:forge_id/config` — Get pipeline configuration
- `PATCH /forges/:forge_id/config` — Update pipeline configuration

**Artifacts**
- `GET /forges/:forge_id/artifacts` — List all artifacts
- `GET /forges/:forge_id/artifacts/:artifact_id` — Get artifact content
- `PATCH /forges/:forge_id/artifacts/:artifact_id` — Update artifact content (manual edit)
- `POST /forges/:forge_id/artifacts/:artifact_id/revise` — Request AI revision with feedback
- `GET /forges/:forge_id/artifacts/:artifact_id/history` — Get artifact version history

**Git**
- `POST /forges/:forge_id/remote` — Configure remote Git URL
- `POST /forges/:forge_id/push` — Push to remote
- `GET /forges/:forge_id/diff/:from_run/:to_run` — Compare artifacts between runs

### GraphQL API (v1)

A GraphQL endpoint at `/api/graphql` provides the same data with flexible querying, nested resolution (e.g., fetch a Forge with its latest run, all artifacts, and their review statuses in a single query), and real-time subscriptions.

### Webhooks

Organizations can configure webhook endpoints that receive POST notifications for:
- Pipeline run completed/failed
- Artifact review requested
- Checkpoint pushed to remote

Webhooks include HMAC signatures for verification and support retry with exponential backoff.

## Technology Stack

### Backend
- **Elixir 1.17+** / **Erlang/OTP 27+**
- **Phoenix 1.7+** (web framework, channels, LiveView)
- **Ecto 3.x** (database layer, migrations, changesets)
- **PostgreSQL 16+** (primary datastore, JSONB, advisory locks)
- **Oban 2.x** (durable job queue for pipeline stages)
- **Broadway** (high-throughput concurrent processing for fan-out)
- **Req** (HTTP client for LLM API calls)
- **Joken** (JWT authentication)
- **Argon2** (password hashing)
- **ExUnit** (testing)
- **Mox** (mock definitions for testing)

### Frontend
- **Phoenix LiveView** (primary UI framework)
- **Tailwind CSS** (styling)
- **Alpine.js** (client-side interactivity where LiveView is insufficient)
- **Monaco Editor** (code artifact editing, embedded via hooks)
- **D3.js or Mermaid** (DAG visualization)

### Infrastructure
- **Docker** (containerized deployment)
- **Fly.io** or **Kubernetes** (orchestration)
- **S3-compatible storage** (large artifact storage, Git repo backups)
- **Redis** (optional: Phoenix PubSub adapter for multi-node deployments)

## Data Model Overview

```
organizations
  |-- has_many: memberships (join table with role)
  |-- has_many: forges
  |-- has_many: api_keys
  |-- has_many: webhook_configs

users
  |-- has_many: memberships
  |-- has_many: sessions

forges
  |-- belongs_to: organization
  |-- has_one: pipeline_config
  |-- has_many: pipeline_runs
  |-- has_many: artifacts
  |-- has_many: component_definitions
  |-- has_many: stage_executions

pipeline_configs
  |-- belongs_to: forge
  |-- has_many: stage_definitions

stage_definitions
  |-- belongs_to: pipeline_config
  |-- has_one: prompt_config

pipeline_runs
  |-- belongs_to: forge
  |-- belongs_to: started_by (user)
  |-- has_many: stage_executions

stage_executions
  |-- belongs_to: forge
  |-- belongs_to: pipeline_run
  |-- belongs_to: artifact (produced)

artifacts
  |-- belongs_to: forge
  |-- has_many: artifact_dependencies (upstream/downstream)
  |-- has_many: review_comments

component_definitions
  |-- belongs_to: forge
  |-- self-referential: parent_component
```

## Pipeline Execution Architecture

### Process Tree (per Pipeline Run)

```
RunSupervisor (DynamicSupervisor)
  |-- RunOrchestrator (GenServer)
  |     Holds run state, coordinates stage sequencing,
  |     handles pause/resume, broadcasts progress
  |
  |-- StageWorker (GenServer, one per active stage execution)
  |     Executes a single stage: builds prompt, calls LLM,
  |     parses output, saves artifact, triggers AI review
  |
  |-- FanOutCoordinator (GenServer, for fan-out stages)
        Manages concurrent entity processing with
        configurable concurrency limits and back-pressure
```

### Execution Flow

1. User calls `POST /forges/:forge_id/runs` with run options
2. Route handler creates a `PipelineRun` record, then starts a `RunSupervisor`
3. `RunOrchestrator` loads the pipeline DAG and finds the first ready stages
4. For each ready stage, `RunOrchestrator` spawns a `StageWorker` (or `FanOutCoordinator` for fan-out stages)
5. `StageWorker` assembles the prompt context from upstream artifacts, calls the LLM, and saves the generated artifact
6. If AI review is enabled, `StageWorker` runs the review prompt and scores the artifact
7. If the score is below auto-approve threshold, the artifact enters `awaiting_review` status
8. If human review is enabled and the configured pause point matches, `RunOrchestrator` pauses and broadcasts `pipeline_paused`
9. When a human submits a review (approve/reject), `RunOrchestrator` resumes:
   - **Approve** — marks artifact approved, finds next ready stages
   - **Reject** — regenerates the artifact with feedback incorporated, returns to step 5
10. When all stages are complete, `RunOrchestrator` triggers the checkpoint (Git commit + manifest), marks the run as completed, and broadcasts `pipeline_completed`

### Fault Tolerance

- If a `StageWorker` crashes, the `RunSupervisor` restarts it with the last known state
- LLM API calls use retry with exponential backoff (configurable: max 3 retries, base delay 2s)
- If a stage fails after all retries, it's marked as `failed` and the user can manually retry
- `RunOrchestrator` state is periodically checkpointed to the database, so runs survive node restarts
- Oban jobs provide at-least-once delivery guarantees for stage executions

## Deployment

### Single-Node (Development / Small Teams)
- Single Docker container running the Phoenix application
- PostgreSQL (can be co-located or external)
- Git repos stored on a mounted volume
- Suitable for up to ~10 concurrent pipeline runs

### Multi-Node (Production / Enterprise)
- Multiple Phoenix nodes behind a load balancer
- PostgreSQL with connection pooling (PgBouncer)
- Distributed Erlang clustering (libcluster with DNS strategy for Kubernetes, or Fly.io internal DNS)
- Horde-based distributed process registry for RunOrchestrators
- Redis-backed Phoenix PubSub for cross-node channel message routing
- S3 for Git repo storage (using git-remote-s3 or similar)
- Suitable for hundreds of concurrent pipeline runs across organizations

### Configuration
- All configuration via environment variables (12-factor app)
- `DATABASE_URL` — PostgreSQL connection string
- `SECRET_KEY_BASE` — Phoenix secret
- `LLM_API_KEY` — Anthropic API key (or per-organization keys)
- `GIT_REPOS_BASE_PATH` — Local path for Git repositories
- `S3_BUCKET` — Optional S3 bucket for Git storage
- `REDIS_URL` — Optional Redis for distributed PubSub
- `OBAN_QUEUES` — Queue configuration (e.g., `pipeline:20,review:5`)

## Non-Functional Requirements

- **Latency** — Pipeline stage transitions under 500ms (excluding LLM call time)
- **Throughput** — Support 100+ concurrent pipeline runs per node
- **Availability** — Zero-downtime deploys via rolling restarts (OTP hot code loading optional)
- **Data Durability** — All state persisted to PostgreSQL; Git commits are durable checkpoints
- **Security** — OWASP top-10 mitigations, encrypted secrets, audit logging, SOC2 readiness
- **Observability** — Structured logging (Logger + JSON formatter), Telemetry metrics (pipeline duration, LLM latency, error rates), OpenTelemetry tracing
- **Testing** — Minimum 80% code coverage, property-based testing for pipeline DAG traversal, integration tests for full pipeline runs with mocked LLM responses
