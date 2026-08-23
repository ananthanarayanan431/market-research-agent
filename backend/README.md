# Agentdrops — Market Research Agent Backend

LangGraph agent (clarify -> brief -> supervisor -> research -> writer) exposed over a single
FastAPI `/chat` endpoint.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows; source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"           # includes native LLM provider SDKs (anthropic, google_genai)
cp .env.example .env              # fill in the required keys, see below
```

## Configuring the LLM

The agent's chat model is provider-agnostic — see `src/agentdrops/agents/llm.py` and
`src/agentdrops/config.py`. Set these in `.env`:

- `LLM_PROVIDER` — `openai` (default, for OpenAI-wire-compatible gateways like OpenRouter,
  Together, Groq, vLLM), `anthropic` (native), or `google_genai` (native).
- `LLM_API_KEY` — key for whichever provider/gateway you picked.
- `LLM_BASE_URL` — gateway URL; only used when `LLM_PROVIDER=openai` (default: OpenRouter).
- `RESEARCH_MODEL` — model id, format depends on provider (see `.env.example` for examples).

Switching providers is a config-only change — no code touches `build_llm()`.

## Infra (postgres, redis, minio)

```bash
docker compose up -d
```

Starts postgres (5432), redis (6379), minio (9000, console 9001) with creds matching
`.env.example` defaults.

## Migrations

```bash
alembic upgrade head
```

Creates the `sessions` and `audit_log` tables (see `src/agentdrops/db/migrations/`). Run once
after `docker compose up -d`, before starting the API — required in dev and in any deploy.

## Run

```bash
uvicorn agentdrops.main:app --reload --port 8001
```

A Celery worker must also be running (`make worker`) — chat turns are enqueued by the API but
executed entirely in the worker process, so no turn ever completes without one.

- `GET /health` — liveness probe.
- `POST /v1/chat` — body `{"message": "...", "thread_id": "<optional, resumes a prior turn>"}`, enqueues a turn and returns immediately.
- `POST /v1/chat/stream` — same body, streams the turn's progress/result via SSE.

## Tests

```bash
pytest
ruff check .
mypy src
```
