# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout

Two independent apps, no shared build:

- `backend/` — Python 3.12, FastAPI + LangGraph. Package `agentdrops`, src-layout under `backend/src/agentdrops/`.
- `frontend/` — Next.js 16 / React 19 / Tailwind v4, App Router, TypeScript. Talks to the backend over HTTP only.
- `docs/superpowers/` — design spec and per-feature implementation plans written before the code. `specs/2026-07-12-deepresearch-market-agent-design.md` is the authoritative design doc.

## Commands

### Backend (run from `backend/`)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"           # includes native provider SDKs (anthropic, google_genai)
cp .env.example .env              # required keys; Settings fails fast if any are missing

docker compose up -d              # postgres 5432, redis 6379, minio 9000/9001 (creds match .env.example)
uvicorn agentdrops.api.main:app --reload --port 8000

pytest                            # asyncio_mode=auto, pythonpath=src — no manual PYTHONPATH
pytest tests/unit/agents/supervisor/test_graph.py::test_name   # single test
ruff check .
mypy src                          # strict mode
```

### Frontend (run from `frontend/`)

```bash
npm install
npm run dev                       # localhost:3000; backend must be on 8000 (CORS is pinned to :3000)
npm run build
npm run lint
```

`NEXT_PUBLIC_API_BASE_URL` overrides the backend origin (defaults to `http://localhost:8000`).

## Backend architecture

The whole system is one compiled LangGraph graph built in `agents/graph.py::build_market_researcher`, with three nested graphs:

```
AgentState:      clarify_with_user → (END if clarification needed) → write_research_brief → supervisor → final_report_generation
SupervisorState:   supervisor ⇄ supervisor_tools   (fans ConductResearch topics out concurrently)
ResearcherState:     llm_call ⇄ tool_node → compress_research   (ReAct loop, one per delegated topic)
```

Each level has its own TypedDict state in `agents/state.py`; the reducers (`add_messages`, `operator.add`) are what make concurrent sub-agent writes safe. Findings flow up by being extracted from the supervisor's `ConductResearch` `ToolMessage`s (`get_notes_from_tool_calls`) into `notes`, which the writer joins into the report.

Key invariants to preserve when editing:

- **Every node builds its LLM through `agents/llm.py::build_llm`** and invokes it through `ainvoke_with_retry`. Provider selection is `settings.llm_provider` dispatched by `init_chat_model` — swapping OpenAI-wire gateways (OpenRouter/Together/Groq/vLLM) for native Anthropic/Gemini is a `.env` change, never a code change. Don't import provider SDKs anywhere; `resilience/llm_retry.py` deliberately duck-types on `status_code` / class-name suffixes to stay provider-agnostic.
- **The `supervisor` node streams its subgraph with `astream`, not `ainvoke`.** A bare nested `ainvoke` starts an isolated run whose `custom` stream writes (progress/source events) never reach the `/chat/stream` consumer. Same reason `run_topic` uses `get_stream_writer()`.
- **`ResearchComplete` does not exit the supervisor loop directly.** Every tool call in a turn must get a matching `ToolMessage` or the LLM API rejects the history; the loop ends on the next turn when the model emits no tool calls.
- Three independent caps in `Settings` bound cost: `max_researcher_iterations` (supervisor turns), `max_concurrent_researchers` (asyncio.Semaphore fan-out), `max_tool_call_iterations` (sub-agent ReAct rounds).

**Search tools** (`webtools/`) subclass `BaseSearchTool` and return `SearchResult`; each applies `HTTP_RETRY` + a named circuit breaker and normalizes failures to `SearchToolError` via `wrap_http_errors`. They are adapted into LangChain tools in `agents/tools.py`, which delegates all search→dedupe→summarize→format work to `agents/research/methods.py::run_search_pipeline`. Adding exa/news/reddit to the agent means appending to the `tools` list in `build_market_researcher` — nothing else changes. `webtools/registry.py::build_search_tools` constructs all four but is not yet wired into the graph.

**API** (`api/main.py`): `_run_graph_turn` is the single caller of `graph.astream`; `/chat` (terminal event only) and `/chat/stream` (SSE, all events) both go through it so session side effects can't diverge. SSE event shapes are documented on `chat_stream` and mirrored in `frontend/src/lib/types.ts` — change both together.

**Persistence is process-local**: `InMemorySaver` checkpointer + in-memory `SessionStore` (`api/sessions.py`). Both die on restart; replace them together if runs need to survive one. `/research/{id}` reads status off the graph checkpoint, but `failed` only exists in the session store.

**Prompts** all live in `agents/prompts.py`; structured-output schemas in `agents/schemas.py`.

## Testing conventions

Tests mirror the source tree under `backend/tests/unit/`. No network: `tests/unit/agents/conftest.py` provides `make_settings(**overrides)` (builds `Settings` with `_env_file=None`) and `FakeChatModel` (scripted responses, supports `bind_tools`/`with_structured_output`). Webtool tests use `respx` against a real `httpx.AsyncClient` and autouse-clear the circuit-breaker registry between tests — breakers are module-global, so a test that trips one will poison later tests without that reset.

## Frontend notes

`frontend/AGENTS.md` (loaded via `frontend/CLAUDE.md`): this is Next.js 16, which has breaking changes vs. older training data — read the relevant guide in `node_modules/next/dist/docs/` before writing Next-specific code.

All state lives in `src/app/page.tsx` (single client component); `Sidebar`/`ChatPanel`/`ResearchDrawer` are presentational. Two concurrency guards there are load-bearing: `selectionTokenRef` (stale session fetches must not clobber a newer selection) and `pollTimeoutRef` (the 3s status poll for reopened running sessions). `src/lib/api.ts` owns all backend calls, including the hand-rolled SSE parser for `/chat/stream`.
