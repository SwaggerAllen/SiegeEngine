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

1. **System Requirements** — document generation with web research
2. **System Architecture** — document + component list extraction
3. **Component Requirements** — fan-out per component
4. **Component Architectures** — fan-out per component
5. **High-Level Plan** — single document
6. **Component Plans** — fan-out per component (+ setup component)
7. **Code Generation** — fan-out, full tool access, git repo, $5 budget
8. **Code Review & Fix** — fan-out, full tool access

Stages 1-6 produce markdown documents via Claude CLI with web research tools.
Stages 7-8 run in the project's git repo with full tool access (bash, file editing).

Fan-out stages extract components from the system architecture (stage 2) using 3-way consensus voting, then run once per component in parallel.

## Key Patterns

- **CLI-based generation**: All LLM calls go through Claude CLI subprocess (`cli/manager.py`), not direct API. Enables tool access, budget control, and reproducibility.
- **Semaphore concurrency**: `MAX_CONCURRENT_LLM_CALLS` (default 5) limits parallel CLI invocations.
- **Review gates**: Pipeline pauses at `awaiting_review` status. Frontend shows ReviewPanel for approve/reject/edit. Resume via `POST /api/pipeline/{project_id}/resume`.
- **Staleness propagation**: Rejecting an artifact marks all downstream artifacts as stale via BFS traversal.
- **Prompt customization**: Each stage's system message, output format, and context template are editable via the PromptEditorPanel and stored in DB (PromptConfig).
- **WebSocket broadcasting**: Pipeline progress events stream to frontend in real-time.
- **Setup component**: `project_setup` is injected for stages 6-8 to ensure scaffolding runs before component code.

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
