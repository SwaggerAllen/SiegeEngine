# SiegeEngine

AI-powered project scaffolding pipeline. Takes a project description and generates system architectures, component designs, implementation plans, and working code through an 8-stage pipeline with AI + human review gates.

## Tech Stack

- **Backend**: Python, FastAPI, SQLAlchemy (SQLite w/ WAL), Claude CLI for all LLM generation
- **Frontend**: React 18, TypeScript, Vite, Zustand, Tailwind CSS, React Flow (DAG), Monaco Editor
- **Deployment**: Fly.io, Docker

## Project Layout

```
siege-engine/
  backend/
    main.py              # FastAPI app entry, lifespan, routes, SPA serving
    config.py            # Settings (SIEGE_ env prefix)
    models.py            # SQLAlchemy ORM (Project, Artifact, Pipeline*, StageExecution)
    database.py          # SQLite + WAL setup
    auth/                # JWT auth, registration, invite links
    chat/                # WebSocket chat with Claude CLI
    cli/manager.py       # Claude CLI subprocess manager (semaphore concurrency)
    dag/service.py       # DAG traversal, staleness propagation
    git_manager/         # GitPython wrapper (commit, diff, push)
    github/              # OAuth + PR creation
    pipeline/
      engine.py          # Orchestrator: sequential stages, fan-out, review gates
      events.py          # Event type constants (RUN_CREATED, STAGE_STARTED, etc.)
      reducer.py         # Pure reducer: apply_event(snapshot, event) → new snapshot
      event_store.py     # Append events, update materialized PipelineSnapshot
      routes.py          # Pipeline API endpoints
      nodes/
        generate.py      # CLI-based artifact generation
        ai_review.py     # AI review feedback generation
        extract_components.py  # 3-way consensus component extraction
      prompts/
        base.py          # PromptTemplate ABC
        requirements.py  # System + component requirements
        architecture.py  # System architecture (outputs component JSON)
        component_arch.py
        high_level_plan.py
        component_plan.py
        codegen.py       # Code generation (full tool access)
        code_review.py   # Code review + auto-fix
        ai_review_prompt.py
    projects/            # Project CRUD
    websocket/           # Real-time pipeline progress broadcasting
  frontend/
    src/
      api/               # Axios client with auth
      components/
        dag/             # PipelineDAG, StageNode (React Flow + Dagre)
        editor/          # ArtifactEditor (Monaco, markdown, diff view)
        pipeline/        # ReviewPanel, StageStatus, PromptEditorPanel
        chat/            # ChatPanel (WebSocket)
      hooks/             # useWebSocket (pipeline progress)
      pages/             # Login, ProjectList, ProjectCreate, ProjectDashboard
      store/             # Zustand: authStore, projectStore, pipelineStore, dagStore
      types/             # TypeScript interfaces
```

## Pipeline Stages

1. **System Requirements** — project-level document generation
2. **System Architecture** — project-level document
3. **Component Extraction** — extracts components via 3-way consensus voting
4. **Component Architectures** — fan-out per component
5. **Sub-Component Extraction** — fan-out per component, extracts sub-components
6. **Component Plans** — fan-out, leaf components only (no sub-components)
7. **Sub-Component Architectures** — fan-out per sub-component
8. **Sub-Component Plans** — fan-out per sub-component
9. **Code Generation** — fan-out per leaf entity, full tool access, git repo, $5 budget
10. **Code Review & Fix** — fan-out per leaf entity, full tool access

Stages 1-8 produce markdown documents via Claude CLI with web research tools.
Stages 9-10 run in the project's git repo with full tool access (bash, file editing).

## Key Patterns

- **Event sourcing**: All pipeline state changes go through events (`pipeline/events.py` → `reducer.py` → `event_store.py`). The `PipelineSnapshot` is the **single source of truth** for pipeline state. DB model status fields (`Artifact.status`, `StageExecution.status`) are projections — written for query convenience but never read for state decisions. The snapshot carries artifact metadata (name, type, component_key via `artifact_meta`), execution mapping (`execution_map`), and all statuses.
- **CLI-based generation**: All LLM calls go through Claude CLI subprocess (`cli/manager.py`), not direct API. Enables tool access, budget control, and reproducibility.
- **Semaphore concurrency**: `MAX_CONCURRENT_LLM_CALLS` (default 5) limits parallel CLI invocations.
- **Review gates**: Pipeline pauses at `awaiting_review` status (read from snapshot). Frontend shows ReviewPanel for approve/reject/edit. Resume via `POST /api/pipeline/{project_id}/resume`.
- **Staleness propagation**: Editing/rejecting an artifact emits `STALENESS_PROPAGATED` events marking downstream artifacts as stale via BFS traversal.
- **Prompt customization**: Each stage's system message, output format, and context template are editable via the PromptEditorPanel and stored in DB (PromptConfig).
- **WebSocket broadcasting**: Pipeline progress events stream to frontend in real-time.
- **Setup component**: `project_setup` is injected for code stages to ensure scaffolding runs before component code.

## Development

```bash
# Backend
source .venv/bin/activate
uvicorn backend.main:app --reload --port 8000

# Frontend
cd siege-engine/frontend && npm run dev   # localhost:5173, proxies to :8000
```

## Environment Variables

All use `SIEGE_` prefix. Key ones: `SIEGE_ANTHROPIC_API_KEY`, `SIEGE_JWT_SECRET_KEY`. See `backend/config.py` for full list.
