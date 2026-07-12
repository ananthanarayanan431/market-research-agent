# Deep Research Market Agent — Design Spec

Date: 2026-07-12

## Problem Statement

How might we build a production-grade, self-service tool that researches a given market/topic in depth (news, web, community sentiment), synthesizes findings into a report, and — using the same divergent/convergent thinking as the `idea-refine` skill — proposes and stress-tests new product/business ideas grounded in that research, all through a web UI?

## Goals

- Given a topic/market (e.g. "AI note-taking apps"), autonomously run a multi-round research process (LangGraph supervisor/researcher pattern) across web search, news, and community sources.
- Synthesize research into a structured final report.
- Run a headless port of `idea-refine`'s three phases (understand & expand → evaluate & converge → sharpen & ship) over that report to produce an idea one-pager.
- Serve this via a Next.js/React web UI with live progress streaming, history of past runs, and export to PDF/Excel.
- Be scalable (stateless API + horizontally scalable workers) and production-quality (typed, tested, observable, migration-managed).

## Non-Goals

- Multi-user auth/permissions (single-operator tool for now).
- Editing/re-running individual research sub-steps after a run completes.
- Real-time collaborative idea refinement (the interactive `idea-refine` Claude Code skill remains available separately for that).

## Architecture Overview

```
Next.js/React  --REST + SSE-->  FastAPI API  --enqueue-->  Redis  --dequeue-->  arq worker(s)
                                     |                                              |
                                     |                                     LangGraph research graph
                                     |                                     (supervisor/researchers/
                                     |                                      idea_refine_generation)
                                     v                                              |
                                 Postgres  <--------- run/event/source/export rows -+
                                     ^
                                     |
                                  MinIO  <--- PDF/XLSX export objects
```

- **Frontend (Next.js/React):** submits runs, subscribes to SSE for live progress, renders final report + idea one-pager, triggers exports, lists history.
- **API (FastAPI):** stateless HTTP layer — validates requests, writes run rows, enqueues jobs, streams progress via SSE, issues presigned MinIO URLs for exports.
- **Worker (arq, Redis-backed):** executes the LangGraph graph per run; horizontally scalable by adding worker replicas; publishes progress events to Redis pub/sub and persists them to Postgres.
- **Postgres:** system of record for run metadata, the full event/audit log, extracted sources, and export records.
- **MinIO:** object storage for generated PDF/Excel exports (and raw research notes dump).
- **Redis:** arq broker + pub/sub transport for live progress relay to SSE.

## Research Graph (LangGraph)

Adapted from `open_deep_research`'s supervisor/researcher pattern:

1. `write_research_brief` — turns the input topic (+ optional constraints) into a structured research brief via structured-output LLM call.
2. `supervisor` / `supervisor_tools` — lead researcher plans strategy, delegates parallel sub-topics to `researcher` subgraphs via a `ConductResearch` tool, uses `think_tool` for strategic reflection between rounds, and a `ResearchComplete` tool to end the phase. Bounded by `max_researcher_iterations` and `max_concurrent_research_units` (configurable).
3. `researcher` / `researcher_tools` (parallel subgraph instances) — each investigates one sub-topic using four search tools: `exa_search` (general web), `tavily_search` (general web, second source for diversity/redundancy), `newsapi_search` (recent news), `reddit_search` (community signal), plus `think_tool`. Runs until its own `ResearchComplete` or `max_react_tool_calls`.
4. `compress_research` — each sub-researcher's raw findings are compressed into a clean summary + raw notes are preserved for citation/export.
5. `final_report_generation` — synthesizes all compressed findings + the research brief into the final market research report (markdown).
6. `idea_refine_generation` (new node) — three sequential structured-output calls over the final report:
   - **Understand & expand:** restate as a "How Might We", generate 5-8 idea variations (inversion, constraint removal, audience shift, combination, simplification, 10x, expert lens), and surface open questions (in place of the interactive skill's clarifying-question step, since this runs headless).
   - **Evaluate & converge:** cluster resonant variations into 2-3 directions, stress-test each on user value / feasibility / differentiation, name hidden assumptions per direction.
   - **Sharpen & ship:** emit the final one-pager — problem statement, recommended direction, key assumptions to validate, MVP scope, "not doing" list, open questions — matching the schema `idea-refine`'s SKILL.md already defines.

Each node emits a progress event (node name, status, short human-readable message) consumed by the worker's event publisher.

Failure handling mirrors the upstream pattern: tool execution errors are captured and returned as `ToolMessage` content (never raise into the graph), and token-limit errors trigger truncate-and-retry in `compress_research` and `final_report_generation`.

## Data Model (Postgres)

- **runs**: `id (uuid pk)`, `topic`, `constraints (jsonb, nullable)`, `status (queued|running|completed|failed)`, `research_brief (text)`, `final_report (text)`, `idea_onepager (jsonb)`, `error (text, nullable)`, `created_at`, `updated_at`.
- **run_events**: `id`, `run_id (fk)`, `node_name`, `event_type`, `message`, `payload (jsonb)`, `created_at` — full audit log; also used to replay history to a client that connects to SSE after a run has already started.
- **sources**: `id`, `run_id (fk)`, `tool_name (exa|tavily|newsapi|reddit)`, `url`, `title`, `snippet`, `retrieved_at` — every citation surfaced during research, used in the report and the Excel export.
- **exports**: `id`, `run_id (fk)`, `format (pdf|xlsx)`, `minio_key`, `generated_at`, `status (generating|ready|failed)`.

Schema is managed with Alembic migrations from day one.

## API Surface (FastAPI)

- `POST /runs` `{topic, constraints?}` → `201 {run_id}` — creates the run row (`status=queued`) and enqueues the arq job.
- `GET /runs` → paginated list for the history page.
- `GET /runs/{id}` → full run detail (status, brief, report, idea one-pager, sources).
- `GET /runs/{id}/events` (SSE) → replays persisted `run_events` for that run, then live-tails the Redis channel until the run reaches a terminal status.
- `POST /runs/{id}/export` `{format: pdf|xlsx}` → creates an `exports` row (`generating`), enqueues export-generation job, returns `{export_id}`.
- `GET /runs/{id}/export/{format}` → `303` redirect to a presigned MinIO URL once `status=ready`, else `202` with current status.

## Export Generation

- **PDF:** render the final report markdown (+ idea one-pager) to HTML then to PDF via WeasyPrint.
- **Excel:** openpyxl workbook with sheets for the report summary, sources (from the `sources` table), and the idea one-pager's assumptions/MVP-scope/not-doing lists as structured rows.
- Both run as a separate arq job (not blocking the research run), write to MinIO, and update the `exports` row to `ready`/`failed`.

## Frontend (Next.js/React)

- **New Run** page: topic input + optional constraints, submits to `POST /runs`, redirects to the run detail page.
- **Run Detail** page: live progress panel driven by SSE (current node, which sub-researcher/source is active), then rendered final report and idea one-pager once complete, with Export PDF/Excel buttons (polls export status, then downloads).
- **History** page: paginated list of past runs (topic, status, date) linking to their detail pages.

## Backend Package Layout

The backend is namespaced under `src/agentdrops` (treating "agentdrops" as the product/company namespace for this and future agents), laid out by responsibility rather than by technical layer alone:

```
backend/
  src/agentdrops/
    __init__.py
    config.py                 # pydantic-settings Settings
    logging.py                 # structlog configuration
    api/
      __init__.py
      app.py                   # FastAPI app factory
      routes/
        runs.py                 # POST/GET /runs, GET /runs/{id}
        events.py                # GET /runs/{id}/events (SSE)
        exports.py               # POST/GET /runs/{id}/export
      schemas/                  # Pydantic request/response models
        runs.py
        exports.py
    webtools/                   # one file per external search tool
      __init__.py
      base.py                    # shared SearchTool protocol/interface + error types
      exa.py
      tavily.py
      news.py                    # NewsAPI
      reddit.py
    research/
      __init__.py
      graph.py                   # LangGraph StateGraph assembly (supervisor/researcher/report)
      state.py                    # AgentState, SupervisorState, ResearcherState, etc.
      prompts.py
      nodes/
        write_research_brief.py
        supervisor.py
        researcher.py
        compress_research.py
        final_report_generation.py
    idearefine/
      __init__.py
      node.py                     # idea_refine_generation graph node
      schemas.py                   # structured-output models for the 3 phases
      prompts.py
    exports/
      __init__.py
      pdf.py                       # WeasyPrint rendering
      xlsx.py                      # openpyxl workbook generation
    storage/
      __init__.py
      postgres/
        models.py                  # SQLAlchemy models
        repositories/               # repository-per-aggregate
          runs.py
          events.py
          sources.py
          exports.py
      minio_client.py
    worker/
      __init__.py
      main.py                      # arq WorkerSettings
      tasks.py                     # run_research_job, generate_export_job
      events.py                     # Redis pub/sub publisher used by graph node callbacks
  tests/
    unit/
    integration/
  alembic/
  pyproject.toml
  Dockerfile
```

Each `webtools/*.py` module implements the same `SearchTool` interface (defined in `webtools/base.py`): an async `search(query: str) -> list[SearchResult]` method plus tool metadata (name, rate-limit config), so the researcher node can bind them to the LLM as tools uniformly and so each is independently unit-testable against mocked HTTP responses.

## Production & Code Quality Standards

- **Python 3.12+, fully typed** — `mypy --strict` in CI; no untyped defs in application code.
- **Pydantic v2** for every I/O boundary: API request/response models, LangGraph structured-output schemas, config.
- **`ruff`** for lint + format, run in pre-commit and CI.
- **Structured logging** (JSON, via `structlog`) correlated by `run_id`, written to stdout for aggregation and mirrored into `run_events` for in-app audit/history.
- **Config via `pydantic-settings`**, all secrets from environment (`.env` locally, real secret store in deployment) — never hardcoded.
- **Repository pattern** for Postgres access (one repository per aggregate: runs, events, sources, exports) so the graph/worker code depends on interfaces, not raw SQL, and is unit-testable with fakes.
- **Alembic** migrations; schema changes never applied by hand.
- **`tenacity`**-based retry/backoff on all external HTTP calls (Exa, NewsAPI, Reddit, Anthropic).
- **Async throughout** the API and worker (SQLAlchemy async engine with pooling, `httpx.AsyncClient`).
- **Horizontal scalability:** FastAPI instances are stateless (all state in Postgres/Redis/MinIO) and can run behind a load balancer; arq workers scale by adding replicas consuming the same Redis queue; Postgres access goes through a bounded connection pool.
- **CI gate:** lint, type-check, unit tests, and a mocked-LLM integration test must pass before merge.

## Error Handling & Resilience

- Search tool failures degrade gracefully (error string returned to the graph, research continues with other sources) rather than failing the whole run.
- LLM token-limit errors trigger truncate-and-retry in compression/report nodes (bounded retry count).
- A run that exhausts retries or hits an unrecoverable error is marked `failed` with `error` populated and surfaced in the UI; partial `run_events` remain visible for debugging.
- Export generation failures are isolated to the `exports` row (`status=failed`) and are independently retryable without re-running research.

## Testing Strategy

- Unit tests per search-tool client (mocked HTTP responses) covering success, empty-result, and error paths.
- Unit tests for the `idea_refine_generation` node's structured-output schemas (valid/invalid shapes).
- Integration test running the full LangGraph graph with a mocked LLM (deterministic fixture responses) asserting the graph reaches `final_report_generation` and `idea_refine_generation` and produces a well-formed one-pager.
- FastAPI `TestClient`/`httpx.AsyncClient` tests for all endpoints, including SSE event replay.
- Repository-layer tests against a real Postgres test database (testcontainers) to catch query/migration issues.
- Frontend smoke test (Playwright) for: create run → see live progress → see final report → export PDF.

## Deployment (docker-compose)

Services: `postgres`, `minio`, `redis`, `backend` (FastAPI API, built from `backend/`), `worker` (arq, same image as backend, different entrypoint), `frontend` (Next.js). Environment variables: `ANTHROPIC_API_KEY`, `EXA_API_KEY`, `TAVILY_API_KEY`, `NEWSAPI_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `DATABASE_URL`, `REDIS_URL`, `MINIO_ENDPOINT`/`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`.

## Key Assumptions to Validate

- [ ] Exa + Tavily + NewsAPI + Reddit's free/dev tiers provide sufficient rate limits for iterative multi-round research — validate during implementation, may need backoff tuning.
- [ ] A headless (non-interactive) idea-refine adaptation still produces useful ideas without the human sharpening-question loop — validate by reviewing early run outputs.
- [ ] WeasyPrint's system dependencies are acceptable in the target container image — validate in the Dockerfile build.

## Not Doing (and Why)

- Multi-tenant auth — out of scope for a single-operator research tool; can be added later behind the same stateless API.
- Editing/resuming a run mid-flight — adds significant state-machine complexity for limited value; re-running from scratch is acceptable at this stage.
- Alternative LLM providers — the graph is built against Claude via the Anthropic API only, matching the rest of this environment.

## Open Questions

- Should exports be generated automatically on run completion, or strictly on-demand (as designed above)? Current design is on-demand to avoid wasted MinIO writes for runs nobody exports.
