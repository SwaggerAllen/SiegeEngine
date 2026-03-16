# SiegeEngine Multi — Project Seed Document

## 1. Project Overview

SiegeEngine Multi is a collaborative, AI-powered project scaffolding and lifecycle management platform. It enables teams of developers to use AI-assisted pipelines to design, build, review, and maintain software projects. The system orchestrates Claude AI through multiple pipeline types — scaffolding new projects, fixing bugs, adding features, and refactoring code — with human review gates and assignable artifact reviews at every stage.

Each team deploys their own independent instance of SiegeEngine Multi. An instance consists of an Elixir umbrella application, a managed PostgreSQL database, and a local Claude CLI installation with its own API keys. Multiple developers share a single instance, collaborating through a shared database and real-time LiveView interface. Cross-instance coordination happens exclusively through a shared git remote (GitHub). There is no shared database, no instance registry, and no service mesh between instances.

The system is a complete rewrite of the original SiegeEngine (a Python/FastAPI/React/SQLite single-user application) into a multi-user Elixir/Phoenix/LiveView/PostgreSQL platform. It retains the core pipeline architecture — an 8-stage scaffolding pipeline with AI generation, AI review, and human review gates — while adding collaboration features, multiple pipeline types, a flow queue, and change propagation.

SiegeEngine Multi is designed to bootstrap itself: the seed document you are reading will be fed into an existing SiegeEngine instance to generate the complete codebase for SiegeEngine Multi. The generated project must be immediately usable for further development on itself using its own bug-fix, feature-add, and refactor pipelines.

---

## 2. Architecture Overview

### 2.1 Deployment Model

Each team deploys their own fully independent instance to Fly.io. An instance is a single Elixir release running on a Fly.io machine with an attached Fly Postgres database and a persistent volume for git repository storage. Claude CLI is installed in the runtime Docker image. Each instance has its own `ANTHROPIC_API_KEY` for Claude CLI invocations and a separate API key (or the same one) for structured data extraction via the Claude HTTP API.

Multiple developers access a single instance through the Phoenix LiveView web interface. They share the same PostgreSQL database and the same local git repository clones. When a pipeline run generates artifacts and code, it commits to a feature branch on the local clone and pushes to the shared GitHub remote. Other developers on the same instance (or other instances connected to the same remote) can pull those changes.

Instances are loosely coupled. The only interaction point between instances is the git remote. Instance A and Instance B can both push branches and create PRs against the same GitHub repository without any direct communication. The database on each instance tracks only that instance's pipeline runs, reviews, and queue state.

### 2.2 Umbrella Application Structure

The application is an Elixir umbrella project with five child applications. Each application has a clear boundary of responsibility and a defined set of dependencies on sibling applications. Applications communicate via direct function calls (not HTTP), since they run in the same BEAM VM.

```
siege_engine_umbrella/
  apps/
    siege_repo/       # Ecto schemas, migrations, shared data access layer
    siege_auth/       # Authentication, authorization, teams, invites, audit log
    siege_git/        # Git operations, branch management, GitHub API integration
    siege_pipeline/   # Pipeline engine, stage execution, CLI manager, flow queue
    siege_web/        # Phoenix LiveView frontend, routes, PubSub, real-time UI
  config/
    config.exs        # Compile-time defaults shared across all apps
    dev.exs           # Local development overrides
    test.exs          # Test environment (sandbox DB, mock CLI)
    prod.exs          # Production compile-time config
    runtime.exs       # Runtime config from environment variables
  mix.exs             # Umbrella root mix file
  .formatter.exs      # Code formatter config
  .credo.exs          # Static analysis config
```

### 2.3 Inter-Application Dependencies

The dependency graph forms a strict DAG with `siege_repo` as the leaf:

```
siege_web -> siege_pipeline, siege_auth, siege_git, siege_repo
siege_pipeline -> siege_git, siege_repo
siege_auth -> siege_repo
siege_git -> siege_repo
siege_repo -> (no sibling dependencies)
```

`siege_repo` owns all Ecto schemas and database migrations. Other apps depend on it for data access but never depend on each other's internal modules — `siege_pipeline` calls `siege_git` public functions for git operations, but `siege_git` never calls back into `siege_pipeline`.

`siege_web` is the only app that depends on all others, since it wires together the UI, authentication, pipeline control, and git operations into LiveView pages.

---

## 3. Technology Stack

### 3.1 Backend

- **Elixir 1.17+** with OTP 27+
- **Phoenix 1.7+** with **Phoenix LiveView 1.0+** as the primary UI framework
- **Ecto 3.12+** with **Postgrex** for PostgreSQL access
- **PostgreSQL 16+** (Fly Postgres managed instance)
- **Oban 2.18+** for background job processing (pipeline execution, flow queue advancement, crash recovery)
- **Guardian 2.3+** for JWT-based authentication (or a lightweight custom JWT implementation using JOSE)
- **Bcrypt_elixir** for password hashing
- **Finch** as the HTTP client for Claude API calls (structured data extraction) and GitHub API
- **Jason** for JSON encoding/decoding
- **Briefly** or **Temp** for temporary file management during CLI operations

### 3.2 Frontend

All UI is rendered via Phoenix LiveView. No separate frontend build process or SPA framework is used.

- **Phoenix LiveView 1.0+** — primary UI framework, handles all page rendering and real-time updates
- **live_monaco_editor** — LiveView component wrapping Monaco Editor for code viewing and editing in the browser, used for artifact content display and review editing
- **dagre-d3** — JavaScript library for DAG visualization, integrated via a LiveView JS hook that receives graph data from the server and renders an interactive pipeline DAG with real-time status updates
- **Tailwind CSS 4.x** — utility-first CSS framework for styling, integrated via the standard Phoenix Tailwind plugin
- **Alpine.js** — minimal JavaScript framework for small interactive behaviors that don't warrant a full LiveView round-trip (dropdowns, tooltips, drag-and-drop in the flow queue)

### 3.3 External Dependencies

- **Claude CLI** — installed in the Docker image, invoked as a subprocess via Elixir's `System.cmd/3` or `Port.open/2` for all document and code generation. Each instance has its own CLI installation with its own API key configured via the `ANTHROPIC_API_KEY` environment variable.
- **Claude HTTP API** (via Anthropic's REST API) — used specifically for structured data extraction (component extraction with 3-way consensus). Called via Finch HTTP client with the `ANTHROPIC_API_KEY`. This is separate from CLI usage because structured extraction needs JSON mode, not CLI text output.
- **GitHub API** — for pushing to remotes, creating pull requests, and optional OAuth login. Accessed via Finch with a user's GitHub access token.
- **Fly.io** — deployment target. The Dockerfile produces a single Elixir release. Fly Postgres provides the managed database. A Fly volume stores git repository clones.

---

## 4. Data Model

All Ecto schemas live in the `siege_repo` application under `SiegeRepo.Schemas.*`. Migrations live in `apps/siege_repo/priv/repo/migrations/`. All tables use UUID primary keys generated by `Ecto.UUID.generate/0`. All timestamps use `utc_datetime_usec` type.

### 4.1 Authentication and Teams

#### Users

```elixir
# Table: users
field :username, :string          # unique, 3-100 chars
field :email, :string             # unique, valid email format
field :password_hash, :string     # bcrypt hash, never exposed
field :instance_role, :string     # "instance_admin" | "member", default "member"
timestamps()                      # inserted_at, updated_at
```

The first user to register on an instance is automatically promoted to `instance_admin`. All subsequent users register as `member`. Instance admins can manage all teams and users on the instance. Regular members can only interact with teams they belong to.

#### Teams

```elixir
# Table: teams
field :name, :string              # display name, 1-100 chars
field :slug, :string              # unique, URL-safe, auto-generated from name
timestamps()
```

Teams are the primary organizational unit. Projects belong to teams. Users access projects through team membership. A user can belong to multiple teams with different roles in each.

#### Team Memberships

```elixir
# Table: team_memberships
belongs_to :team, Team
belongs_to :user, User
field :role, :string              # "owner" | "maintainer" | "contributor" | "reviewer" | "viewer"
field :inserted_at, :utc_datetime_usec
```

Unique constraint on `{team_id, user_id}`. The user who creates a team is automatically assigned the `owner` role. Roles determine permissions per the permission matrix in section 6.

#### Invite Links

```elixir
# Table: invite_links
belongs_to :team, Team
belongs_to :created_by, User
field :token, :string             # unique, 64-char random hex
field :role, :string              # role to assign on registration: same options as team_memberships
field :expires_at, :utc_datetime_usec  # default 24 hours from creation
field :used_at, :utc_datetime_usec     # nullable, set when used
belongs_to :used_by, User              # nullable, set when used
timestamps()
```

Invite links are the only way to add users to a team (besides instance admin direct assignment). An invite link encodes a specific team and role. When a new user registers via an invite link, they are added to the team with the specified role. If the user already has an account, they can use the invite link to join the team.

#### GitHub Credentials

```elixir
# Table: github_credentials
belongs_to :user, User            # unique (one credential per user)
field :access_token, :string      # encrypted at rest
field :github_username, :string   # nullable
timestamps()
```

GitHub OAuth tokens are per-user and used for pushing to remotes and creating PRs. The access token should be encrypted using Elixir's built-in `:crypto` module with a key derived from `SECRET_KEY_BASE`.

#### Audit Log

```elixir
# Table: audit_log
belongs_to :team, Team
belongs_to :user, User
field :action, :string            # e.g., "artifact.approved", "pipeline.started", "review.assigned"
field :resource_type, :string     # e.g., "artifact", "pipeline_run", "stage_execution"
field :resource_id, Ecto.UUID
field :metadata, :map             # JSONB, action-specific details
field :inserted_at, :utc_datetime_usec
```

Every significant action is recorded in the audit log. The audit log is append-only (no updates or deletes). It is used for team accountability and debugging pipeline issues. The `metadata` field contains action-specific details (e.g., for `artifact.approved`: `%{"artifact_name" => "...", "reviewer_notes" => "..."}` ).

### 4.2 Projects

```elixir
# Table: projects
belongs_to :team, Team
field :name, :string              # display name
field :slug, :string              # unique within team, URL-safe
field :description, :string       # nullable, text
field :git_repo_path, :string     # absolute path to local git clone
field :remote_url, :string        # nullable, GitHub HTTPS URL
field :github_repo_slug, :string  # nullable, "owner/repo" format
field :default_branch, :string    # default "main"
timestamps()
```

Unique constraint on `{team_id, slug}`. Each project has exactly one local git repository clone stored at `git_repo_path`. The repository is initialized on project creation. If a `remote_url` is provided, the remote is configured as `origin`.

### 4.3 Pipeline System

#### Pipeline Types

```elixir
# Table: pipeline_types
field :key, :string               # unique: "scaffold", "bug_fix", "feature_add", "refactor"
field :name, :string              # display name: "Scaffold", "Bug Fix", "Feature Add", "Refactor"
field :description, :string       # text description of what this pipeline type does
timestamps()
```

Pipeline types are seeded on first deployment and are instance-global (not per-team or per-project). They define the available pipeline workflows. Each pipeline type has a set of stage definitions that describe the ordered stages of that workflow.

#### Stage Definitions

```elixir
# Table: stage_definitions
belongs_to :pipeline_type, PipelineType
field :stage_key, :string         # unique within pipeline_type, e.g., "system_requirements"
field :display_name, :string      # e.g., "System Requirements"
field :order_index, :integer      # determines execution order (lower = earlier)
field :output_artifact_type, :string  # the artifact_type this stage produces
field :input_stage_keys, {:array, :string}  # list of stage_keys this stage depends on
field :fan_out_strategy, :string  # "none" | "component" | "sub_component"
field :ai_review_enabled, :boolean  # default true
field :human_review_enabled, :boolean  # default true
field :propagation_direction, :string  # "downstream" | "upstream" | "none"
field :tools, :string             # "WebFetch,WebSearch" or "default"
field :model, :string             # default "claude-sonnet-4-20250514"
field :timeout_seconds, :integer  # default 600 for doc stages, 1200 for code stages
field :max_budget_usd, :decimal   # nullable, used for code stages
timestamps()
```

Unique constraint on `{pipeline_type_id, stage_key}`. Stage definitions are seeded alongside pipeline types. They are not editable through the UI (they are configuration, not user data).

#### Prompt Templates

```elixir
# Table: prompt_templates
belongs_to :stage_definition, StageDefinition  # unique (one template per stage)
field :system_message, :string    # text, the system prompt sent to Claude
field :output_format_instructions, :string  # text, appended to system message
field :context_template, :string  # text, template for the user message with {placeholders}
field :revision_instructions, :string  # text, appended when revising after rejection
field :formatting_guidance, :string  # text, formatting rules appended to all prompts
timestamps()
```

Prompt templates are seeded with the stage definitions. They contain the full prompt text for each pipeline stage. Placeholder variables in `context_template` include `{input_artifacts}`, `{component_key}`, `{artifact_content}`, `{feedback}`, `{previous_version}`, and `{code_diff}`. The pipeline engine performs string interpolation on these templates before sending to Claude CLI.

#### Pipeline Runs

```elixir
# Table: pipeline_runs
belongs_to :project, Project
belongs_to :pipeline_type, PipelineType
belongs_to :started_by, User
field :run_number, :integer       # auto-increment per project (across all pipeline types)
field :status, :string            # "pending" | "running" | "paused" | "completed" | "failed" | "cancelled"
field :git_branch, :string        # e.g., "siege/scaffold/run-1"
field :started_at, :utc_datetime_usec
field :completed_at, :utc_datetime_usec  # nullable
timestamps()
```

Each pipeline run operates on a dedicated git branch. The branch name follows the pattern `siege/{pipeline_type_key}/{run_number}`. The run_number is globally unique per project (not per pipeline type) to avoid branch name collisions.

Only one pipeline run may be active per project at a time. Additional runs are queued via the flow queue system (section 9).

#### Stage Executions

```elixir
# Table: stage_executions
belongs_to :pipeline_run, PipelineRun
belongs_to :stage_definition, StageDefinition
belongs_to :artifact, Artifact        # nullable, set after generation
belongs_to :assigned_reviewer, User   # nullable
belongs_to :reviewed_by, User         # nullable, set after review
field :component_key, :string         # nullable, for fan-out stages
field :status, :string
  # "pending" | "queued" | "running" | "ai_review" | "awaiting_review"
  # | "approved" | "rejected" | "failed" | "skipped" | "stale"
field :error_message, :string         # nullable, text
field :retry_count, :integer          # default 0
field :started_at, :utc_datetime_usec # nullable
field :completed_at, :utc_datetime_usec  # nullable
timestamps()
```

Stage executions track the status of each stage within a pipeline run. For fan-out stages (those with `fan_out_strategy` of `component` or `sub_component`), there is one stage execution per component or sub-component. The `assigned_reviewer_id` field enables the review assignment system — when a stage execution reaches `awaiting_review` status, the assigned reviewer is notified via PubSub.

### 4.4 Artifacts

```elixir
# Table: artifacts
belongs_to :project, Project
belongs_to :pipeline_run, PipelineRun
field :artifact_type, :string     # matches stage_definition.output_artifact_type
field :name, :string              # display name
field :component_key, :string     # nullable, for component-scoped artifacts
field :content, :string           # text, the full artifact content (markdown or code)
field :status, :string
  # "pending" | "generating" | "ai_reviewing" | "awaiting_review"
  # | "approved" | "rejected" | "stale"
field :version, :integer          # default 1, incremented on each regeneration
field :file_path, :string         # path within git repo (e.g., "requirements/system_requirements.md")
field :git_commit_sha, :string    # nullable, SHA of the commit containing this artifact
field :ai_review_feedback, :string  # nullable, text of AI review
field :human_review_notes, :string  # nullable, text
field :previous_version_id, Ecto.UUID  # nullable, FK to artifacts.id for version tracking
timestamps()
```

Artifacts are the primary work products of the pipeline. Each stage execution produces one artifact. Artifacts are committed to git with the path specified in `file_path`. When an artifact is regenerated (after rejection), the `version` field is incremented and `previous_version_id` points to the prior version. This enables version comparison and in-place modification tracking.

#### Artifact Dependencies

```elixir
# Table: artifact_dependencies
belongs_to :upstream_artifact, Artifact
belongs_to :downstream_artifact, Artifact
field :dependency_type, :string   # "input" | "propagation"
```

Tracks the dependency graph between artifacts. `input` dependencies mean the downstream artifact was generated using the upstream artifact as input context. `propagation` dependencies mean changes to the upstream artifact should trigger updates to the downstream artifact (used for change propagation in sections 5.2-5.4).

#### Artifact Comments

```elixir
# Table: artifact_comments
field :artifact_id, Ecto.UUID     # NOT a foreign key — persists across artifact regenerations
belongs_to :project, Project
belongs_to :author, User          # nullable (null for system events)
field :content, :string           # text
field :comment_type, :string      # "comment" | "review_note" | "system_event"
field :parent_id, Ecto.UUID       # nullable, FK to artifact_comments.id for threading
field :artifact_version, :integer # nullable, the artifact version this comment was made on
timestamps()
```

Comments are intentionally not foreign-keyed to the artifacts table because artifacts may be regenerated (deleted and recreated). The `artifact_id` is stored as a plain UUID that persists across regenerations. Comments made on version 1 of an artifact remain visible when viewing version 2.

#### Component Definitions

```elixir
# Table: component_definitions
belongs_to :project, Project
belongs_to :pipeline_run, PipelineRun
field :key, :string               # snake_case identifier, unique within {project, pipeline_run}
field :name, :string              # human-readable name
field :description, :string       # text
field :parent_key, :string        # nullable, for sub-component relationships
field :dependencies, {:array, :string}  # list of sibling component keys this depends on
timestamps()
```

Component definitions are extracted from the system architecture artifact during stage 2 of the scaffold pipeline. They define the components that fan-out stages iterate over. The extraction uses a 3-way consensus mechanism (section 11.3) to ensure reliable component identification.

### 4.5 Flow Queue

```elixir
# Table: flow_queue
belongs_to :project, Project
belongs_to :pipeline_type, PipelineType
belongs_to :requested_by, User
field :priority, :integer         # default 0, higher = execute sooner
field :status, :string            # "queued" | "active" | "completed" | "cancelled"
field :context, :map              # JSONB — pipeline-type-specific context
  # scaffold: %{"seed_document" => "..."}
  # bug_fix: %{"bug_report_id" => "..."}
  # feature_add: %{"feature_description" => "..."}
  # refactor: %{"refactor_description" => "...", "scope" => "..."}
field :started_at, :utc_datetime_usec  # nullable
field :completed_at, :utc_datetime_usec  # nullable
timestamps()
```

The flow queue ensures only one pipeline run is active per project at a time. When a user requests a new pipeline run while one is already active, the request is added to the queue. When the active run completes, the next queued flow (by priority, then insertion order) is automatically started.

#### Bug Reports

```elixir
# Table: bug_reports
belongs_to :project, Project
belongs_to :flow_queue_entry, FlowQueue  # nullable, set when queued for fix
belongs_to :reported_by, User
field :title, :string
field :description, :string       # text
field :reproduction_steps, :string  # nullable, text
field :affected_components, {:array, :string}  # list of component keys
field :severity, :string          # "critical" | "high" | "medium" | "low"
field :status, :string            # "reported" | "triaged" | "in_progress" | "fixed" | "verified" | "wont_fix"
timestamps()
```

Bug reports are a first-class entity. They can be filed independently of pipeline runs and optionally queued for automated fixing via the bug fix pipeline. When a bug fix flow is queued, the `flow_queue_entry` association links the bug report to the queue entry, which contains the bug report ID in its `context` map.

---

## 5. Pipeline Type Definitions

All four pipeline types are seeded into the `pipeline_types` and `stage_definitions` tables on first deployment. Each stage definition has an associated prompt template seeded into the `prompt_templates` table.

### 5.1 Scaffold Pipeline

The scaffold pipeline takes a project from a seed document to a fully generated, reviewed codebase. It has 8 stages that execute in dependency order, with fan-out on component-scoped stages.

**Stage 1: system_requirements**

- Input: project seed document (stored in `flow_queue.context.seed_document`)
- Output artifact type: `system_requirements`
- Fan-out: none
- Tools: `WebFetch,WebSearch`
- Human review: yes
- AI review: yes
- Propagation: downstream
- Timeout: 600 seconds

The system prompt instructs Claude to act as a senior requirements engineer analyzing the seed document. The output is a structured markdown document with sections for project purpose, functional requirements, non-functional requirements, data requirements, integration dependencies, constraints, edge cases, and success criteria. Claude is instructed to go beyond what is explicitly stated — inferring implicit requirements, identifying edge cases, and flagging assumptions.

**Stage 2: system_architecture**

- Input: system_requirements artifact
- Output artifact type: `system_architecture`
- Fan-out: none
- Tools: `WebFetch,WebSearch`
- Human review: yes
- AI review: yes
- Propagation: downstream
- Timeout: 600 seconds

The system prompt instructs Claude to act as a senior software architect designing a production system. The output is a structured markdown document covering system overview, component breakdown, data flow, technology choices, non-functional architecture, and deployment architecture.

After this stage is approved, the pipeline automatically runs the component extraction process (section 11.3) to identify the components from the architecture document. The extracted components are stored as `ComponentDefinition` records and used for fan-out in subsequent stages.

**Stage 3: component_requirements**

- Input: system_requirements, system_architecture
- Output artifact type: `component_requirements` (one per component)
- Fan-out: component
- Tools: `WebFetch,WebSearch`
- Human review: yes
- AI review: yes
- Propagation: downstream
- Timeout: 600 seconds

For each component extracted in stage 2, Claude generates a detailed requirements document covering the component's purpose, functional requirements, interface requirements, data requirements, performance requirements, error handling, security, and dependencies.

**Stage 4: component_architecture**

- Input: system_architecture, component_requirements (for this component)
- Output artifact type: `component_architecture` (one per component)
- Fan-out: component
- Tools: `WebFetch,WebSearch`
- Human review: yes
- AI review: yes
- Propagation: downstream
- Timeout: 600 seconds

For each component, Claude generates an architecture document covering internal module breakdown, public API and interfaces, data models, dependencies, error handling, and testing strategy.

**Stage 5: high_level_plan**

- Input: system_architecture, system_requirements, all approved component_architecture artifacts
- Output artifact type: `high_level_plan`
- Fan-out: none
- Tools: `WebFetch,WebSearch`
- Human review: yes
- AI review: yes
- Propagation: downstream
- Timeout: 600 seconds

Claude generates an overall delivery plan covering implementation phases, component delivery order, integration milestones, risk assessment, key technical decisions, and testing strategy.

**Stage 6: component_plan**

- Input: high_level_plan, component_architecture (for this component), component_requirements (for this component)
- Output artifact type: `component_plan` (one per component)
- Fan-out: component
- Tools: `WebFetch,WebSearch`
- Human review: yes
- AI review: yes
- Propagation: downstream
- Timeout: 600 seconds

For each component, Claude generates an implementation plan with a file inventory (every file to create or modify), implementation order, unit test plan, and integration points.

**Stage 7: code_generation**

- Input: component_plan (for this component), component_architecture (for this component)
- Output artifact type: `code` (one per component)
- Fan-out: component
- Tools: `default` (full tool access — Bash, Edit, Read, Write, Glob, Grep)
- Human review: yes
- AI review: no (code review is a separate stage)
- Propagation: upstream
- Timeout: 1200 seconds
- Max budget: $5.00 USD

Claude generates complete, runnable code for each component. The CLI is invoked with `--tools default` which gives Claude access to the filesystem. The `working_dir` is set to the project's git repository path so Claude can create and edit files directly. Claude is instructed to generate production-quality code following language idioms, with proper error handling and inline comments for complex logic.

After code generation, the pipeline extracts code files from the working directory (not from markdown code blocks) and commits them to the run's git branch.

**Stage 8: code_review**

- Input: component_plan (for this component), generated code files
- Output artifact type: `code_review` (one per component)
- Fan-out: component
- Tools: `default` (full tool access)
- Human review: yes
- AI review: no
- Propagation: upstream
- Timeout: 1200 seconds
- Max budget: $5.00 USD

Claude reviews all code files for the component, fixes bugs, runs tests if available, and produces a review summary with issues found, fixes applied, and a recommendation (approve/revise with quality score). This stage has full filesystem access so it can modify the generated code in-place.

### 5.2 Bug Fix Pipeline

The bug fix pipeline takes a bug report and produces a targeted fix with documentation updates. It has 5 stages.

**Stage 1: bug_triage**

- Input: bug report content, existing system_architecture, affected component architecture docs, existing codebase (via filesystem access)
- Output artifact type: `bug_triage`
- Fan-out: none
- Tools: `default` (needs to read codebase to analyze root cause)
- Human review: yes
- AI review: no
- Propagation: downstream
- Timeout: 600 seconds

The system prompt instructs Claude to act as a senior engineer triaging a bug report. Claude reads the bug report, examines the relevant code and architecture docs, and produces a triage report containing: root cause analysis, affected files and components, fix strategy (what needs to change), risk assessment, and estimated complexity.

The context template for this stage includes the bug report content from `flow_queue.context` and references to the project's existing architecture documents.

**Stage 2: fix_plan**

- Input: bug_triage artifact, relevant component_plan and component_architecture docs
- Output artifact type: `fix_plan`
- Fan-out: none
- Tools: `default`
- Human review: yes
- AI review: no
- Propagation: downstream
- Timeout: 600 seconds

Claude produces a specific fix plan: which files to modify, what changes to make in each, and how to verify the fix works. The plan should reference specific functions, modules, and line numbers in the existing codebase.

**Stage 3: fix_implementation**

- Input: fix_plan artifact, existing codebase
- Output artifact type: `fix_code` (one per affected component if multiple)
- Fan-out: component (affected components only, identified in the triage stage)
- Tools: `default`
- Human review: yes
- AI review: no
- Propagation: upstream
- Timeout: 900 seconds
- Max budget: $3.00 USD

Claude implements the fix by modifying existing code files. The emphasis is on minimal, targeted changes — not rewriting files. Claude should make the smallest change that correctly fixes the bug.

**Stage 4: fix_review**

- Input: fix_plan, code changes (git diff)
- Output artifact type: `fix_review` (one per affected component)
- Fan-out: component
- Tools: `default`
- Human review: yes
- AI review: no
- Propagation: upstream
- Timeout: 600 seconds
- Max budget: $2.00 USD

Claude reviews the fix, verifies it addresses the root cause identified in the triage, checks for regressions, and runs tests if available.

**Stage 5: doc_update**

- Input: code changes (git diff from fix), existing architecture/plan/requirements docs
- Output artifact type: `doc_update` (one per affected component)
- Fan-out: component
- Tools: `WebFetch,WebSearch`
- Human review: yes
- AI review: no
- Propagation: none (terminal stage)
- Timeout: 600 seconds

Claude examines the code changes and updates the relevant documentation in-place. The prompt includes the current document content and the code diff, with instructions to make targeted modifications to specific sections rather than regenerating the entire document. This is critical for producing clean PR diffs.

The system prompt for this stage must emphasize:
- Only modify sections that are actually affected by the code change
- Preserve the existing document structure and heading hierarchy
- Make the minimum necessary changes to keep documentation accurate
- Do not rewrite sections that are still correct

### 5.3 Feature Add Pipeline

The feature add pipeline extends an existing project with new functionality. It has 6 stages.

**Stage 1: feature_requirements**

- Input: feature description (from `flow_queue.context.feature_description`), existing system_architecture
- Output artifact type: `feature_requirements`
- Fan-out: none
- Tools: `WebFetch,WebSearch`
- Human review: yes
- AI review: yes
- Propagation: downstream
- Timeout: 600 seconds

Claude analyzes the feature request against the existing system architecture and produces a requirements document for the new feature. The requirements should identify which existing components are affected and what new components (if any) are needed.

**Stage 2: feature_architecture**

- Input: feature_requirements, existing system_architecture
- Output artifact type: `feature_architecture`
- Fan-out: none
- Tools: `WebFetch,WebSearch`
- Human review: yes
- AI review: yes
- Propagation: downstream
- Timeout: 600 seconds

Claude produces an architecture delta — not a replacement of the full system architecture, but a document describing what changes to the architecture are needed for this feature. This includes: new components (if any), modifications to existing component interfaces, new data models or changes to existing ones, and new communication patterns.

**Stage 3: feature_plan**

- Input: feature_architecture, existing component_plans for affected components
- Output artifact type: `feature_plan` (one per affected component)
- Fan-out: component (affected components, identified in feature_architecture)
- Tools: `WebFetch,WebSearch`
- Human review: yes
- AI review: no
- Propagation: downstream
- Timeout: 600 seconds

For each affected component, Claude produces an implementation plan describing what files to create or modify, what code to add or change, and what tests to write.

**Stage 4: feature_implementation**

- Input: feature_plan, existing codebase
- Output artifact type: `feature_code` (one per affected component)
- Fan-out: component
- Tools: `default`
- Human review: yes
- AI review: no
- Propagation: upstream
- Timeout: 1200 seconds
- Max budget: $5.00 USD

Claude implements the feature by creating new files and modifying existing ones. For existing files, Claude should make targeted modifications rather than rewriting entire files.

**Stage 5: feature_review**

- Input: feature_plan, code changes
- Output artifact type: `feature_review` (one per affected component)
- Fan-out: component
- Tools: `default`
- Human review: yes
- AI review: no
- Propagation: upstream
- Timeout: 600 seconds
- Max budget: $3.00 USD

Claude reviews the feature implementation, runs tests, and produces a review report.

**Stage 6: doc_update**

- Input: code changes, existing architecture/plan/requirements docs
- Output artifact type: `doc_update` (one per affected component)
- Fan-out: component
- Tools: `WebFetch,WebSearch`
- Human review: yes
- AI review: no
- Propagation: none
- Timeout: 600 seconds

Same as the bug fix doc_update stage — targeted in-place modifications to keep documentation consistent with code changes.

### 5.4 Refactor Pipeline

The refactor pipeline restructures existing code without changing functionality. It has 4 stages.

**Stage 1: refactor_analysis**

- Input: refactor description (from `flow_queue.context.refactor_description`), existing system_architecture, existing codebase
- Output artifact type: `refactor_analysis`
- Fan-out: none
- Tools: `default` (needs filesystem access to analyze code)
- Human review: yes
- AI review: yes
- Propagation: downstream
- Timeout: 600 seconds

Claude analyzes the codebase in the context of the refactor request and produces an analysis covering: what to change, why, affected components, risk assessment, and a proposed approach. The analysis should justify the refactoring and identify potential regressions.

**Stage 2: refactor_plan**

- Input: refactor_analysis, existing component_plans for affected components
- Output artifact type: `refactor_plan`
- Fan-out: none
- Tools: `default`
- Human review: yes
- AI review: no
- Propagation: downstream
- Timeout: 600 seconds

Claude produces an ordered refactoring plan with specific steps, a rollback strategy (how to undo each step if something goes wrong), and verification criteria for each step.

**Stage 3: refactor_implementation**

- Input: refactor_plan, existing codebase
- Output artifact type: `refactor_code` (one per affected component)
- Fan-out: component (affected components)
- Tools: `default`
- Human review: yes
- AI review: no
- Propagation: upstream
- Timeout: 1200 seconds
- Max budget: $5.00 USD

Claude implements the refactoring. For refactors, it is especially important that changes are made incrementally and that each intermediate state is valid (compiles, passes tests).

**Stage 4: doc_update**

- Input: refactored code changes, existing docs
- Output artifact type: `doc_update` (one per affected component)
- Fan-out: component
- Tools: `WebFetch,WebSearch`
- Human review: yes
- AI review: no
- Propagation: none
- Timeout: 600 seconds

Same as other doc_update stages.

---

## 6. Authentication and Permission Model

### 6.1 Authentication

Authentication uses JWT tokens. Users log in with username and password. The server returns a JWT containing the user ID and username, signed with `GUARDIAN_SECRET`. Tokens expire after 24 hours. The LiveView socket validates the token on mount and stores the authenticated user in socket assigns.

Registration flow:
1. First user on the instance registers freely and is auto-promoted to `instance_admin`
2. All subsequent users must register using an invite link that specifies the team and role
3. If a user already has an account, they can use an invite link to join an additional team

### 6.2 Instance-Level Permissions

| Action | instance_admin | member |
|--------|:-:|:-:|
| Manage all users (reset password, deactivate) | Yes | No |
| Create teams | Yes | Yes |
| View all teams | Yes | No (only their own) |
| System configuration | Yes | No |

### 6.3 Team-Level Permissions

Permissions are checked per team membership role. A user can have different roles in different teams.

| Action | owner | maintainer | contributor | reviewer | viewer |
|--------|:-:|:-:|:-:|:-:|:-:|
| Create project in team | Yes | Yes | No | No | No |
| Delete project | Yes | No | No | No | No |
| Update project settings | Yes | Yes | No | No | No |
| Start pipeline run | Yes | Yes | Yes | No | No |
| Cancel active pipeline run | Yes | Yes | No | No | No |
| Assign reviewers to stages | Yes | Yes | No | No | No |
| Review artifacts (when assigned) | Yes | Yes | Yes | Yes | No |
| Approve/reject artifacts | Yes | Yes | Yes | Yes | No |
| File bug reports | Yes | Yes | Yes | Yes | No |
| Queue new flows | Yes | Yes | Yes | No | No |
| Reorder/cancel queued flows | Yes | Yes | No | No | No |
| Add comments on artifacts | Yes | Yes | Yes | Yes | No |
| View project, artifacts, DAG | Yes | Yes | Yes | Yes | Yes |
| Push to git remote | Yes | Yes | Yes | No | No |
| Create pull requests | Yes | Yes | Yes | No | No |
| Manage team members | Yes | Yes | No | No | No |
| Generate invite links | Yes | Yes | No | No | No |
| Delete team | Yes | No | No | No | No |

### 6.4 Review Assignment

Reviewers are assigned at the stage execution level. When a stage execution transitions to `awaiting_review`:

1. If `assigned_reviewer_id` is set on the stage execution, only that user can approve/reject
2. If no reviewer is assigned, any team member with review permission can "claim" the review by clicking a "Claim Review" button, which sets `assigned_reviewer_id` to their user ID
3. Once claimed, only the claiming reviewer (or a maintainer+) can approve/reject
4. Maintainers and owners can reassign reviews to a different user
5. All review actions are recorded in the audit log

---

## 7. Git Workflow

### 7.1 Repository Management

Each project has a local git repository clone stored at `{SIEGE_GIT_REPOS_PATH}/{project_id}`. The repository is initialized on project creation with `git init`. If a `remote_url` is provided, the remote `origin` is configured immediately.

Git operations are implemented in the `siege_git` application using Elixir's `System.cmd/3` to invoke the `git` CLI. The `siege_git` app exposes a public API module (`SiegeGit.Operations`) with functions for:

- `init_repo(path)` — initialize a new git repository
- `configure_remote(repo_path, remote_url)` — set the origin remote
- `create_branch(repo_path, branch_name, base_ref)` — create and checkout a new branch
- `checkout(repo_path, branch_name)` — checkout an existing branch
- `commit(repo_path, file_paths, message)` — stage specific files and commit
- `commit_all(repo_path, message)` — stage all changes and commit
- `push(repo_path, branch_name, access_token)` — push branch to remote (using token in URL)
- `diff(repo_path, from_ref, to_ref)` — get diff between two refs
- `file_content_at_ref(repo_path, file_path, ref)` — read file content at a specific commit
- `log(repo_path, branch, limit)` — get commit log
- `current_branch(repo_path)` — get current branch name
- `merge_base(repo_path, branch_a, branch_b)` — find common ancestor

### 7.2 Branch Strategy

- `main` (or whatever `project.default_branch` is set to) — protected, only updated via merged PRs
- `siege/{pipeline_type_key}/run-{run_number}` — one branch per pipeline run
  - Examples: `siege/scaffold/run-1`, `siege/bug_fix/run-3`, `siege/feature_add/run-5`
- Each branch is created from the tip of `default_branch` at the time the pipeline run starts
- All artifact commits during a run go to the run's branch
- On run completion (all stages approved), the system auto-creates a PR against `default_branch`

### 7.3 Commit Convention

Each artifact commit follows this format:

```
[siege:{pipeline_type}:{stage_key}] {artifact_name}

Component: {component_key}
Run: #{run_number}
Stage: {stage_display_name}
Reviewed-by: {reviewer_username}
```

For stages that generate code files (stages 7-8 of scaffold, fix_implementation, feature_implementation, refactor_implementation), the commit includes all files created or modified by that stage execution, not just the artifact content file.

### 7.4 In-Place Modification

When a stage execution is re-run after rejection (or during change propagation), the system uses in-place modification instead of full regeneration:

1. Load the previous artifact content from the database (`previous_version_id`)
2. Include it in the prompt as the "current version" of the document
3. Include the rejection feedback or change propagation context
4. Instruct Claude to make targeted modifications to specific sections, not regenerate the entire document
5. Commit the modified artifact as a new commit on the same branch (not force-push, not amend)
6. The git diff between the old and new commit shows exactly what changed

This produces clean, reviewable PR diffs where reviewers can see the evolution of each document across revisions.

### 7.5 Pull Request Creation

When all stage executions in a pipeline run reach `approved` status:

1. Push the run's branch to the remote (if configured)
2. Create a PR via the GitHub API using the project owner's GitHub credentials
3. PR title: `[SiegeEngine] {pipeline_type_name}: {brief_description}`
   - For scaffold: `[SiegeEngine] Scaffold: Initial project generation`
   - For bug fix: `[SiegeEngine] Bug Fix: {bug_report_title}`
   - For feature add: `[SiegeEngine] Feature: {feature_description_summary}`
   - For refactor: `[SiegeEngine] Refactor: {refactor_description_summary}`
4. PR body: auto-generated markdown summarizing all artifacts in the run — stage names, artifact names, reviewer names, approval timestamps
5. PR labels: `siege-engine`, `{pipeline_type_key}`

---

## 8. Change Propagation

Change propagation ensures that documentation stays consistent with code changes. The propagation direction varies by pipeline type.

### 8.1 Downstream Propagation (Scaffold Pipeline)

In the scaffold pipeline, changes flow top-down: requirements inform architecture, architecture informs plans, plans inform code. When a stage 1-6 artifact is rejected and regenerated, all downstream artifacts that depend on it are marked as `stale` via BFS traversal of the `artifact_dependencies` graph.

Staleness propagation:
1. When an artifact is rejected, traverse `artifact_dependencies` where `dependency_type = "input"` in the downstream direction
2. Mark each downstream artifact as `stale`
3. Mark each corresponding stage execution as `stale`
4. Stale artifacts must be regenerated (using in-place modification with the updated upstream as context) before the run can complete
5. Regeneration of stale artifacts uses the existing artifact content as the base, modifying it to reflect changes from the updated upstream artifact

### 8.2 Upstream Propagation (Bug Fix, Feature Add, Refactor)

In non-scaffold pipelines, code changes trigger documentation updates. The `doc_update` stage is the terminal stage in all three non-scaffold pipeline types.

When code stages (fix_implementation, feature_implementation, refactor_implementation) are approved:
1. The pipeline engine identifies which documentation artifacts are affected based on the component key
2. The `doc_update` stage execution(s) are created with status `pending`
3. The prompt for doc_update includes:
   - The current documentation content (loaded from the latest approved artifact for that component)
   - The code diff (git diff between the pre-change and post-change states)
   - Instructions to make targeted, in-place modifications to the affected sections
4. The updated documentation is committed to the same run branch
5. Human review is required before the doc updates are considered final

### 8.3 Significance Assessment

Not every code change warrants a documentation update. The `doc_update` prompt template includes instructions for Claude to assess whether the documentation actually needs changes:

- If the code change is purely internal (renamed variable, refactored implementation without API changes), Claude should state "no documentation changes needed" and the artifact is marked as a no-op
- If the code change affects public interfaces, data models, or architectural decisions, Claude should update the relevant sections
- Claude should never rewrite sections that are unaffected by the change

---

## 9. Flow Queue System

### 9.1 Core Behavior

Only one pipeline run may be active per project at a time. This constraint exists because pipeline runs operate on the project's git repository, and concurrent runs on different branches would create filesystem conflicts.

When a user requests a new pipeline run while one is already active:
1. A `flow_queue` entry is created with status `queued`
2. The entry stores the full context needed to start the run (seed document for scaffold, bug report ID for bug fix, feature description for feature add, refactor description for refactor)
3. The user sees their queued flow in the flow queue UI

When the active pipeline run completes (status becomes `completed`, `failed`, or `cancelled`):
1. The flow queue is checked for the next entry (ordered by priority descending, then `inserted_at` ascending)
2. If a queued entry exists, it is promoted to `active` and the corresponding pipeline run is started automatically
3. This is handled by an Oban worker that runs on pipeline completion

### 9.2 Queue Management

- Users with `queue` permission can view and reorder the queue via the UI (drag-and-drop with Alpine.js)
- Reordering updates the `priority` field
- Users with `cancel_queue` permission can cancel queued entries (status → `cancelled`)
- Maintainers and owners can force-start a queued flow, which cancels the active run first (with confirmation)
- The queue is displayed per-project in the project dashboard

### 9.3 Oban Workers

The flow queue uses Oban for reliable background processing:

- `SiegePipeline.Workers.QueueAdvancer` — triggered when a pipeline run completes; checks for next queued flow and starts it
- `SiegePipeline.Workers.StageRunner` — executes individual pipeline stages; scheduled by the pipeline engine
- `SiegePipeline.Workers.CrashRecovery` — periodic job (every 5 minutes) that marks stuck stage executions (running for > timeout + buffer) as failed and triggers queue advancement if needed

---

## 10. Real-Time Communication

### 10.1 Phoenix PubSub Topics

All real-time updates are delivered via Phoenix PubSub, which LiveView subscribes to automatically. No separate WebSocket protocol is needed — LiveView handles this natively.

Topic structure:
- `"project:{project_id}"` — project-level events (new pipeline run started, queue changes)
- `"pipeline_run:{pipeline_run_id}"` — run progress (stage transitions, completion)
- `"artifact:{artifact_id}"` — artifact updates (content changed, status changed, new comments)
- `"user:{user_id}:reviews"` — review assignment notifications for a specific user
- `"team:{team_id}:activity"` — team activity feed (audit log events)

### 10.2 Event Types

Events broadcast on PubSub:
- `{:stage_started, stage_execution}` — a stage has begun executing
- `{:stage_completed, stage_execution}` — a stage execution finished (moved to ai_review or awaiting_review)
- `{:stage_failed, stage_execution, error}` — a stage execution failed
- `{:artifact_updated, artifact}` — artifact content or status changed
- `{:review_assigned, stage_execution, reviewer}` — a reviewer was assigned or changed
- `{:review_completed, stage_execution, reviewer, decision}` — a review was submitted
- `{:pipeline_completed, pipeline_run}` — all stages complete
- `{:pipeline_paused, pipeline_run}` — pipeline waiting for reviews
- `{:queue_updated, project_id, queue_entries}` — flow queue changed
- `{:comment_added, comment}` — new comment on an artifact

### 10.3 LiveView Pages

All pages are LiveView modules under `SiegeWeb.Live.*`:

```
/                                     — redirect to /projects
/login                                — SiegeWeb.Live.LoginLive
/register/:invite_token               — SiegeWeb.Live.RegisterLive
/projects                             — SiegeWeb.Live.ProjectListLive (team project list)
/projects/new                         — SiegeWeb.Live.ProjectCreateLive
/projects/:team_slug/:project_slug    — SiegeWeb.Live.ProjectDashboardLive
  (shows: active run status, DAG, recent activity, queue)
/projects/:team_slug/:project_slug/runs/:run_number
                                      — SiegeWeb.Live.PipelineRunLive
  (shows: full DAG, stage executions, artifact list)
/projects/:team_slug/:project_slug/artifacts/:id
                                      — SiegeWeb.Live.ArtifactDetailLive
  (shows: Monaco editor with content, review panel, comments)
/projects/:team_slug/:project_slug/bugs
                                      — SiegeWeb.Live.BugListLive
/projects/:team_slug/:project_slug/bugs/new
                                      — SiegeWeb.Live.BugReportFormLive
/projects/:team_slug/:project_slug/queue
                                      — SiegeWeb.Live.FlowQueueLive
/reviews                              — SiegeWeb.Live.UserReviewDashboardLive
  (shows: all pending reviews assigned to current user across all projects)
/admin/users                          — SiegeWeb.Live.Admin.UsersLive (instance_admin only)
/admin/teams                          — SiegeWeb.Live.Admin.TeamsLive (instance_admin only)
```

### 10.4 LiveView Components

Reusable LiveView components under `SiegeWeb.Components.*`:

- **PipelineDAG** — LiveView hook component wrapping dagre-d3. Receives graph data (nodes with status, edges with dependency type) from the server as JSON. Renders an interactive SVG DAG with color-coded nodes (green=approved, yellow=in-progress, red=failed, gray=pending, orange=awaiting-review). Updates in real-time when PubSub events change node statuses. Nodes are clickable and navigate to the artifact detail page.

- **ArtifactEditor** — Wraps `live_monaco_editor` to display artifact content with syntax highlighting (markdown for documents, language-appropriate for code). Includes a toggle between rendered markdown preview and raw editor view. Read-only by default; editable only during review by the assigned reviewer.

- **ReviewPanel** — Displayed alongside the ArtifactEditor when a stage execution is in `awaiting_review` status and the current user is the assigned reviewer (or the review is unclaimed). Contains: approve button, reject button with required feedback textarea, claim button (if unclaimed), and a notes field for optional reviewer comments. All actions emit PubSub events and create audit log entries.

- **FlowQueuePanel** — Displays the ordered list of queued flows for a project. Each entry shows pipeline type, description, requested by, and priority. Supports drag-and-drop reordering (Alpine.js) for users with reorder permission. Cancel button per entry for users with cancel permission.

- **StageProgress** — Shows the execution status of a stage: a progress indicator while running (with elapsed time), streaming log output if available, and final status with duration when complete.

- **CommentThread** — Threaded comment display for an artifact. Shows comments grouped by version with timestamps and author names. New comment form at the bottom. Supports reply-to-comment threading via `parent_id`.

- **BugReportForm** — Structured form for filing bug reports: title, description (textarea), reproduction steps (textarea), affected components (multi-select populated from `component_definitions`), severity (dropdown). On submit, creates a `bug_report` record and optionally queues a bug fix flow.

- **UserReviewBadge** — Small badge shown in the navigation header displaying the count of pending reviews assigned to the current user. Clicking navigates to `/reviews`. Updates in real-time via PubSub subscription to `"user:{user_id}:reviews"`.

---

## 11. CLI Manager

### 11.1 Architecture

The CLI manager lives in the `siege_pipeline` application at `SiegePipeline.CLI.Manager`. It is a GenServer that manages concurrent Claude CLI subprocess invocations with configurable concurrency limits.

The GenServer maintains a pool of available "slots" (default 5, configurable via `SIEGE_MAX_CONCURRENT_CLI`). When a generation request arrives and all slots are occupied, the request is queued internally and processed when a slot becomes available.

### 11.2 Public API

```elixir
defmodule SiegePipeline.CLI.Manager do
  @doc """
  Generate text output from Claude CLI.
  Used for document stages (1-6) and doc_update stages.
  """
  def generate(opts) :: {:ok, String.t()} | {:error, String.t()}
    # opts:
    #   prompt: String.t() (required)
    #   system_prompt: String.t() | nil
    #   working_dir: String.t() | nil
    #   model: String.t() | nil (default from config)
    #   tools: String.t() | nil (e.g., "WebFetch,WebSearch")
    #   timeout_ms: integer() | nil (default 600_000)
    #   max_budget_usd: Decimal.t() | nil

  @doc """
  Generate code with full tool access.
  Used for code stages (7-8) and fix/feature/refactor implementation stages.
  """
  def generate_code(opts) :: {:ok, String.t()} | {:error, String.t()}
    # opts:
    #   prompt: String.t() (required)
    #   system_prompt: String.t() | nil
    #   working_dir: String.t() (required — git repo path)
    #   model: String.t() | nil
    #   max_budget_usd: Decimal.t() | nil (default 5.0)
    #   timeout_ms: integer() | nil (default 1_200_000)
end
```

### 11.3 CLI Invocation

The underlying subprocess invocation builds a command like:

```bash
claude -p "{prompt}" \
  --output-format text \
  --system-prompt "{system_prompt}" \
  --model "claude-sonnet-4-20250514" \
  --tools "WebFetch,WebSearch" \
  --dangerously-skip-permissions \
  --no-session-persistence
```

For code generation stages, `--tools default` replaces the specific tool list, and `--max-budget-usd {budget}` is added.

The environment is set with `ANTHROPIC_API_KEY` from the application config. The `CLAUDECODE` environment variable is explicitly removed to prevent interference.

The subprocess is managed via `System.cmd/3` with a Task that enforces the timeout. If the process exceeds the timeout, it is killed via `System.cmd("kill", [pid])`.

### 11.4 Structured Data Extraction (HTTP API)

For extracting structured data (component lists from architecture documents, recommendation scores from reviews), the system uses the Claude HTTP API directly, not the CLI. This is because the CLI outputs text, while the API supports JSON mode for reliable structured output.

```elixir
defmodule SiegePipeline.Extractor do
  @doc """
  Extract component definitions from an architecture document.
  Uses Claude API with JSON mode for reliable structured output.
  """
  def extract_components(architecture_content) ::
    {:ok, [%{key: String.t(), name: String.t(), description: String.t(), dependencies: [String.t()]}]}
    | {:error, String.t()}

  @doc """
  Run extraction 3 times and take the majority consensus.
  Ensures reliable component identification by voting on the result.
  """
  def extract_components_consensus(architecture_content) ::
    {:ok, [component_definition()]} | {:error, String.t()}
end
```

The consensus mechanism runs 3 independent extraction calls in parallel (using `Task.async_stream/3`), then compares results by component keys. A component is included in the final list if it appears in at least 2 of the 3 extractions. Dependency lists are merged from all extractions that include the component.

---

## 12. Configuration

### 12.1 Environment Variables

```
# Database
DATABASE_URL=postgres://user:pass@host:5432/siege_engine_multi

# Phoenix
SECRET_KEY_BASE=...                     # minimum 64 bytes, generated by mix phx.gen.secret
PHX_HOST=siege-multi.fly.dev            # production hostname
PORT=4000                               # HTTP port

# Auth
GUARDIAN_SECRET=...                      # JWT signing key, separate from SECRET_KEY_BASE

# Claude
ANTHROPIC_API_KEY=...                   # used by both CLI and HTTP API extraction
CLAUDE_CLI_PATH=claude                  # path to claude binary (default: "claude" on PATH)
SIEGE_MAX_CONCURRENT_CLI=5              # max parallel CLI processes
SIEGE_DEFAULT_MODEL=claude-sonnet-4-20250514

# GitHub
GITHUB_CLIENT_ID=...                   # for OAuth login flow
GITHUB_CLIENT_SECRET=...
GITHUB_REDIRECT_URI=...

# Git
SIEGE_GIT_REPOS_PATH=/app/data/repos   # base directory for project git repos

# Fly.io (set automatically by Fly)
FLY_APP_NAME=...
```

### 12.2 Application Config

```elixir
# config/config.exs
config :siege_repo, SiegeRepo.Repo,
  migration_primary_key: [type: :binary_id],
  migration_timestamps: [type: :utc_datetime_usec]

config :siege_web, SiegeWeb.Endpoint,
  live_view: [signing_salt: "..."]

config :siege_pipeline,
  default_model: "claude-sonnet-4-20250514",
  max_concurrent_cli: 5,
  cli_timeout_document: 600_000,
  cli_timeout_code: 1_200_000

# config/runtime.exs parses all environment variables into application config
```

---

## 13. Seed Data

The `priv/repo/seeds.exs` file in `siege_repo` populates the database with all pipeline type definitions, stage definitions, and prompt templates. This is the data that makes the system functional out of the box.

### 13.1 Pipeline Types

Four pipeline types are seeded:

1. **scaffold** — "Scaffold" — "Generate a complete project from a seed document through 8 stages: requirements, architecture, component extraction, component requirements, component architecture, high-level plan, component plans, code generation, and code review."
2. **bug_fix** — "Bug Fix" — "Take a bug report through triage, fix planning, implementation, review, and documentation update."
3. **feature_add** — "Feature Add" — "Add new functionality through requirements, architecture delta, planning, implementation, review, and documentation update."
4. **refactor** — "Refactor" — "Restructure existing code through analysis, planning, implementation, and documentation update."

### 13.2 Stage Definitions and Prompt Templates

Each pipeline type's stages (as defined in section 5) are seeded as `stage_definitions` records with associated `prompt_templates`. The prompt templates contain the full text of system messages, output format instructions, context templates, and revision instructions.

The scaffold pipeline prompt templates are ported directly from the original SiegeEngine's `defaults.yaml` file, adapted for the Elixir context (references to Phoenix, LiveView, Ecto patterns where the original references Python/FastAPI).

The bug fix, feature add, and refactor pipeline prompt templates are new and follow the same style — detailed system messages instructing Claude on its role, structured output format instructions with markdown heading hierarchies, and context templates with placeholder variables.

The shared formatting guidance (applied to all document stages across all pipeline types):

```
FORMATTING REQUIREMENTS — follow these strictly for readability:

- Leave a blank line before and after every heading (##, ###).
- Use ### subsections within each ## section to break up long sections. Do not write a ## section as a single wall of text.
- Keep paragraphs short — 3 to 5 sentences maximum. Insert a blank line between paragraphs.
- Use **bold** for key terms, names, and important concepts on their first mention.
- Use `inline code` for technical identifiers (file names, function names, config keys, etc.).
- Use horizontal rules (---) to separate major thematic sections when it aids scanning.
- When listing 3+ parallel items, use a bullet list or numbered list instead of embedding them in a run-on sentence. Follow each list with a blank line.
- Avoid dense blocks of text. Aim for a document that is easy to scan and has clear visual hierarchy.
```

The shared revision instructions (appended when re-generating after rejection):

```
REVISION REQUESTED.
Address all issues raised in the feedback and produce an improved version.
Preserve the existing document structure. Only modify sections that need to change based on the feedback. Do not rewrite sections that are already correct.
```

### 13.3 Self-Bootstrapping Seed Data

In addition to pipeline configuration, the seeds file creates the initial data needed for the application to develop itself:

1. A default team called "SiegeEngine Team"
2. An invite link for the first developer to register
3. A project called "SiegeEngine Multi" with:
   - `slug`: "siege-engine-multi"
   - `git_repo_path`: pointing to the application's own repository
   - `remote_url`: the application's own GitHub remote
   - `default_branch`: "main"
4. Pre-populated `component_definitions` matching the umbrella apps:
   - `siege_repo` — "Siege Repo" — "Ecto schemas, migrations, and shared data access layer"
   - `siege_auth` — "Siege Auth" — "Authentication, authorization, teams, invites, and audit log"
   - `siege_git` — "Siege Git" — "Git operations, branch management, and GitHub API integration"
   - `siege_pipeline` — "Siege Pipeline" — "Pipeline engine, stage execution, CLI manager, and flow queue"
   - `siege_web` — "Siege Web" — "Phoenix LiveView frontend, routes, PubSub, and real-time UI"
   - Dependencies: `siege_auth -> [siege_repo]`, `siege_git -> [siege_repo]`, `siege_pipeline -> [siege_git, siege_repo]`, `siege_web -> [siege_pipeline, siege_auth, siege_git, siege_repo]`

This means that after running `mix ecto.setup`, a developer can immediately start a bug fix, feature add, or refactor pipeline run against the SiegeEngine Multi codebase itself.

---

## 14. Document Structure Templates

Each artifact type has a defined heading structure. These templates are embedded in the prompt template's `output_format_instructions` field. The AI is instructed to follow this structure exactly, which ensures that:

1. Documents are consistently structured across components and across regeneration cycles
2. In-place modifications can target specific sections by heading
3. PR diffs show changes at the section level, not as whole-document replacements
4. Change propagation can identify which sections of a parent document are affected by a child change

### 14.1 System Requirements Structure

```
# System Requirements: {project_name}

## Project Purpose and Scope
## Functional Requirements
### {requirement_category_1}
### {requirement_category_2}
## Non-Functional Requirements
### Performance
### Scalability
### Security
### Availability
## Data Requirements
## Integration and External Dependencies
## Constraints and Assumptions
## Edge Cases and Risk Areas
## Success Criteria
```

### 14.2 System Architecture Structure

```
# System Architecture: {project_name}

## System Overview
## Component Breakdown
### {component_1}
### {component_2}
## Data Flow and Communication
## Technology Choices
## Non-Functional Architecture
### Scalability
### Reliability
### Security
### Observability
## Deployment Architecture
```

### 14.3 Component Requirements Structure

```
# Component Requirements: {component_name}

## Component Purpose
## Functional Requirements
### {capability_1}
### {capability_2}
## Interface Requirements
## Data Requirements
## Performance and Scalability Requirements
## Error Handling and Resilience
## Security Requirements
## Dependencies and Constraints
```

### 14.4 Component Architecture Structure

```
# Component Architecture: {component_name}

## Component Purpose and Responsibilities
## Internal Module Breakdown
### {module_1}
### {module_2}
## Public API and Interfaces
## Data Models
## Dependencies and Integration
## Error Handling and Resilience
## Testing Strategy
```

### 14.5 Component Plan Structure

```
# Implementation Plan: {component_name}

## File Inventory
### {file_path_1}
### {file_path_2}
## Implementation Order
### Step 1: {description}
### Step 2: {description}
## Unit Test Plan
### {test_file_1}
### {test_file_2}
## Integration Points
```

### 14.6 Bug Triage Structure

```
# Bug Triage: {bug_title}

## Bug Summary
## Root Cause Analysis
## Affected Files and Components
## Fix Strategy
## Risk Assessment
## Estimated Complexity
```

### 14.7 Fix/Feature/Refactor Plan Structure

```
# {Type} Plan: {title}

## Overview
## Changes Required
### {file_or_component_1}
### {file_or_component_2}
## Implementation Steps
### Step 1: {description}
### Step 2: {description}
## Verification Criteria
## Rollback Strategy (refactor only)
```

### 14.8 Doc Update Structure

Doc updates do not have their own structure — they modify existing documents in-place, preserving the original document's heading structure.

---

## 15. Testing Strategy

### 15.1 Unit Tests

Each umbrella app has its own test suite under `apps/{app}/test/`.

**siege_repo tests:**
- Ecto changeset validations (required fields, format constraints, uniqueness)
- Schema relationships and associations
- Custom Ecto types (if any)

**siege_auth tests:**
- Password hashing and verification
- JWT token creation and validation
- Permission checks: test every cell in the permission matrix
- Invite link generation, validation, and expiry
- Team membership role transitions

**siege_pipeline tests:**
- Pipeline engine stage ordering logic (given a set of stage definitions, verify correct execution order)
- Fan-out logic (given component definitions, verify correct stage execution creation)
- Staleness propagation (reject an artifact, verify downstream artifacts are marked stale)
- Flow queue ordering (verify priority + insertion order)
- Prompt template variable interpolation
- CLI manager argument building (verify correct CLI flags for different stage types)
- Component extraction consensus (mock 3 API responses, verify voting logic)
- In-place modification prompt construction (verify previous version is included)

**siege_git tests:**
- All git operations against a temporary repository (created in test setup, cleaned up in teardown)
- Branch creation and checkout
- Commit and diff
- File content at specific refs
- These tests use real `git` commands, not mocks

**siege_web tests:**
- LiveView page rendering (verify correct HTML output)
- LiveView event handling (simulate button clicks, form submissions)
- PubSub integration (broadcast an event, verify LiveView updates)
- Permission-gated UI (verify that viewers cannot see approve/reject buttons)
- Navigation and routing

### 15.2 Integration Tests

Integration tests verify the interaction between umbrella apps:

- **Full pipeline run** (with mocked CLI responses): start a scaffold pipeline, mock CLI generate to return predefined content, verify stage transitions, verify artifact creation, verify git commits on the correct branch
- **Review workflow**: start a run, advance to awaiting_review, assign reviewer, approve, verify next stage starts
- **Rejection and staleness**: approve stage 1, reject stage 2, verify stage 3+ artifacts are stale, re-run stage 2, verify stale artifacts are regenerated
- **Flow queue**: start a run, queue another, complete first, verify second starts automatically
- **Bug fix flow**: create bug report, queue fix, verify pipeline starts with bug report context

### 15.3 Test Infrastructure

- **ExUnit** with async tests where possible (each test in its own DB sandbox)
- **Ecto SQL Sandbox** for database isolation between tests
- **Mox** for mocking the CLI manager in pipeline tests (define a behaviour for `SiegePipeline.CLI.ManagerBehaviour` and mock it in tests)
- **Temporary git repos** created with `System.cmd("git", ["init", tmp_path])` in test setup
- **Factory module** using ExMachina for generating test data (users, teams, projects, artifacts)

---

## 16. Deployment

### 16.1 Dockerfile

Multi-stage Dockerfile:

```
# Stage 1: Build
FROM hexpm/elixir:1.17-erlang-27-debian-bookworm as build
# Install build deps, copy mix files, fetch deps, compile
# Compile assets (Tailwind, esbuild for JS hooks)
# Build release with MIX_ENV=prod

# Stage 2: Runtime
FROM debian:bookworm-slim
# Install runtime deps: libstdc++, openssl, git, curl
# Install Claude CLI (curl install script or download binary)
# Copy release from build stage
# Set environment variables
# Create data directory for git repos
CMD ["/app/bin/siege_engine_umbrella", "start"]
```

Key points:
- Git must be installed in the runtime image (used by `siege_git`)
- Claude CLI must be installed in the runtime image
- The release uses `mix release` with the umbrella configuration
- Assets are compiled during the build stage

### 16.2 fly.toml

```toml
app = "siege-engine-multi"
primary_region = "ord"

[build]

[env]
  PHX_HOST = "siege-engine-multi.fly.dev"
  PORT = "4000"
  SIEGE_GIT_REPOS_PATH = "/app/data/repos"

[http_service]
  internal_port = 4000
  force_https = true

[[mounts]]
  source = "siege_data"
  destination = "/app/data"

[deploy]
  release_command = "/app/bin/migrate"
```

The `migrate` script runs `SiegeRepo.Repo.Migrator.up()` and the seeds file on deploy. A persistent volume at `/app/data` stores git repository clones that survive deploys.

### 16.3 Fly Postgres

Attached via `fly postgres attach`. The `DATABASE_URL` is automatically set by Fly. Connection pool size should be configured in `runtime.exs` based on the Fly machine size (default: 10 connections).

---

## 17. File Organization in Git Repos

Each project's git repository follows this directory structure for pipeline-generated files:

```
requirements/
  system_requirements.md
  components/
    {component_key}.md
architecture/
  system_architecture.md
  components/
    {component_key}.md
plans/
  high_level_plan.md
  components/
    {component_key}.md
code/
  {component_key}/
    {actual source files as determined by the implementation plan}
components/
  component_map.md
bugs/
  {bug_id}/
    report.md
    triage.md
    fix_plan.md
features/
  {feature_slug}/
    requirements.md
    architecture.md
    plan.md
refactors/
  {refactor_slug}/
    analysis.md
    plan.md
siege-state.json
```

The `siege-state.json` file is a manifest committed at the end of each pipeline run. It contains:
- Pipeline type and run number
- List of all artifacts with their statuses, versions, and git commit SHAs
- Component definitions with dependencies
- Timestamp of completion

This file enables other instances (connected to the same git remote) to understand what pipeline runs have been completed and what the current state of the project is, without needing access to the originating instance's database.

---

## 18. Development Setup

After cloning the repository and running the initial setup, a developer should be able to start working immediately:

```bash
# Prerequisites: Elixir 1.17+, PostgreSQL 16+, Claude CLI, Node.js (for asset compilation)

# Install dependencies
mix deps.get

# Create database, run migrations, seed pipeline types + self-bootstrapping data
mix ecto.setup

# Install JS dependencies for LiveView hooks (dagre-d3, Monaco)
cd apps/siege_web/assets && npm install && cd ../../..

# Start the development server
mix phx.server

# Visit http://localhost:4000
# Register as the first user (auto-promoted to instance_admin)
# The "SiegeEngine Multi" project is already created, pointing at this repo
# Start a bug fix or feature add pipeline to develop further
```

The `mix ecto.setup` task runs:
1. `mix ecto.create` — create the database
2. `mix ecto.migrate` — run all migrations
3. `mix run apps/siege_repo/priv/repo/seeds.exs` — seed pipeline types, stage definitions, prompt templates, and the self-bootstrapping project data
