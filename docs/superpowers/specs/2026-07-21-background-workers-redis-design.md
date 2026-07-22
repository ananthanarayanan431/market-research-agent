---
# Background Workers + Redis Job State — Design Spec

Date: 2026-07-21

## Problem Statement

A research run (`build_market_researcher`'s compiled LangGraph) is a long-running process — a full turn spans clarification, brief-writing, multi-round supervised research fan-out, and report synthesis. Today, `/chat` and `/chat/stream` in `backend/src/agentdrops/api/main.py` drive `graph.astream` directly inside the HTTP request coroutine (`_run_graph_turn`), and all state is process-local:

- `InMemorySaver` (`agents/graph.py`) holds LangGraph's own checkpoint state.
- `SessionStore` (`api/sessions.py`) is a plain in-memory `dict`, and per `CLAUDE.md`, is the *only* place `status == "failed"` is recorded — everything else is derived live from the checkpoint.

Both die on process restart, and neither is shared across replicas. This means the backend cannot run more than one process/replica, and every research run ties up its HTTP request/connection for the run's full duration.

`docker-compose.yml` already provisions Postgres and Redis; `Settings` already requires `redis_url` and `database_url`. Neither is wired to anything in `src/` today — this spec wires them in.

## Goals

- Move graph execution off the HTTP request path and into separate worker processes (Celery), so the API layer only enqueues work and reports status.
- Make all state needed to resume or report on a run shared across processes, enabling horizontal scaling of both the API and the workers.
- Preserve the existing frontend experience (live SSE streaming during an active turn, 3s polling reattachment for reopened running sessions) without requiring frontend code changes.
- Consolidate today's two-source status model (in-memory `SessionStore` for `failed`, checkpoint for everything else) into one source of truth.

## Non-Goals

- Retry/max-runtime policy tuning for Celery tasks — left as an implementation-time decision (default Celery behavior is an acceptable starting point).
- Any frontend changes — the SSE event shapes and polling contract are unchanged by design.
- Zero-downtime cutover — this is a one-time breaking migration (see Rollout).
- Multi-user auth/permissions, exports, or any other scope from `2026-07-12-deepresearch-market-agent-design.md` not directly related to job execution/state.

## Relationship to the Prior Design Doc

`2026-07-12-deepresearch-market-agent-design.md` (the authoritative design doc) already envisions a Redis/Postgres-backed worker architecture using `arq`, as part of a larger scope (MinIO exports, idea-refine generation, Postgres-backed run/event audit log). The current codebase implements neither that worker split nor Postgres/Redis wiring — it still runs everything in-process with `InMemorySaver`.

This spec implements the worker/persistence slice of that architecture as its own focused change, using **Celery** instead of `arq` (an explicit choice for this iteration, trading async-native simplicity for Celery's maturity/ecosystem). It intentionally leaves out the Postgres run/event audit log and MinIO export pieces from the prior doc — those remain future work, not part of this change.

## Architecture Overview

```
                    ┌─────────────┐
  Browser  ──────►  │  FastAPI    │
                    │  (API proc) │
                    └──────┬──────┘
                           │ enqueue task(thread_id, turn input)
                           ▼
                    ┌─────────────┐        ┌──────────────┐
                    │ Redis        │◄──────►│ Celery worker │
                    │ - broker     │ pub/   │ (N replicas)  │
                    │ - result bkd │ sub    │ runs the      │
                    │ - job status │ status │ compiled      │
                    │   hash       │ writes │ LangGraph     │
                    └──────┬──────┘        └──────┬───────┘
                           │ subscribe                │ checkpoints
                           ▼                           ▼
                    SSE relay to browser         ┌─────────────┐
                                                  │  Postgres    │
                                                  │ (checkpointer)│
                                                  └─────────────┘
```

**Components:**

- **API process (FastAPI):** thin. `/chat` and `/chat/stream` enqueue a Celery task carrying `thread_id` + turn input; neither calls `graph.astream` directly anymore.
- **Celery workers:** a new, separate process (own container/replica set), the *only* code path that calls `graph.astream`/`ainvoke`. As a worker drives a turn, it writes progress into the Redis job-status hash and publishes each event on a Redis pub/sub channel keyed by `thread_id`.
- **Redis:** three roles — Celery broker + result backend, the pub/sub bus for live events, and the durable job-status hash that both `/research/{id}` and the SSE relay read from.
- **Postgres:** LangGraph checkpointer backend (`langgraph-checkpoint-postgres`), replacing `InMemorySaver`. Invisible to the API layer — exists purely so any worker replica can resume a thread's graph state on a later turn (e.g., after a clarification round-trip ends the graph early).
- **`/chat/stream`:** becomes a Redis pub/sub subscriber that relays messages as SSE, in the same wire format the frontend already parses (`frontend/src/lib/api.ts`'s `streamChat()` is unchanged).

## Redis Job-State Schema

Key `job:{thread_id}` (hash):

```
status      "queued" | "running" | "clarifying" | "done" | "failed"
title       str
created_at  iso timestamp
report      str | null       (set on done)
sources     JSON array       (appended as research turns discover them)
error       str | null       (set on failed)
```

Plus a per-thread pub/sub channel `events:{thread_id}` carrying the same `progress` / `source` / `clarify` / `done` / `error` payloads the frontend already parses.

Redis becomes the **single source of truth** for API-facing status. Postgres checkpoint state is purely the worker's internal resumption mechanism and is never read by the API layer — this removes today's hybrid `get_research_status` logic (checkpoint-derived `running`/`clarifying`/`done` + session-store-derived `failed`) in favor of one read path.

## Data Flow

**Normal turn (new message):**
1. `POST /chat/stream` writes `status=queued` to `job:{thread_id}`, enqueues a Celery task `run_turn(thread_id, input)`, then subscribes to `events:{thread_id}` and starts relaying as SSE.
2. The worker picks up the task, sets `status=running`, and drives `graph.astream(...)` — the same logic `_run_graph_turn` has today — except each event is published to `events:{thread_id}` *and* used to update the Redis hash (`sources` appended; `report`/`status` set on terminal events) instead of being yielded to a local generator.
3. On the terminal event, the worker sets `status=done` (or `clarifying`/`failed`) and publishes a final message; the API's subscriber sees the terminal event and closes the SSE stream.

**Clarify turn:** identical mechanics — the task ends after publishing a `clarify` event and setting `status=clarifying`. No special-casing needed since Redis is already the single status source.

**Reopening a still-running session** (the `pollTimeoutRef` path in `frontend/src/app/page.tsx`): unchanged from the frontend's perspective. `GET /research/{id}` reads straight from the `job:{thread_id}` Redis hash — simpler than today's checkpoint+session-store hybrid read, and no live SSE subscription is needed for this path (poll-only, as today).

**Race handling:** `/chat/stream`'s subscriber must handle the task having already finished by the time it subscribes (enqueue-then-subscribe race) — it checks the Redis hash for a terminal `status` first, and only falls through to pub/sub streaming if still `queued`/`running`/`clarifying`.

## API Contract Changes

- **`/chat` (non-streaming): breaking change.** Today it blocks until the whole turn finishes and returns the terminal event (`ChatResponse`). Under this design it cannot block on worker completion without reintroducing the problem being solved, so it changes to enqueue-and-return: responds immediately with `{thread_id, status: "queued"}`. Callers needing the final result poll `/research/{id}`.
- **`/chat/stream`:** same request contract (SSE), internally now a Redis pub/sub subscriber instead of a direct graph driver.
- **`/research/{thread_id}`:** same response shape, now sourced purely from the Redis hash; the `graph.aget_state` call is removed from this path entirely.

## Error Handling

- Any exception inside the worker task is caught, written as `status=failed` + `error` message into the Redis hash, and an `error` event is published — mirroring `/chat/stream`'s existing `except Exception` branch today, moved into the worker.
- Worker crash/timeout with no chance to self-report failure (killed process, OOM) is a known gap: a Celery-level safeguard (task time limit, and reconciling a Celery `FAILURE`/`REVOKED` result back into the Redis hash) is needed, but the specific policy (timeout values, retry counts) is left for implementation time, not fixed here.
- If the Redis connection drops mid-stream, the SSE subscriber should emit an `error` event to the client rather than hang indefinitely.

## Testing

- Per `backend/tests/unit/` conventions ("no network"): Celery task-body tests run in `task_always_eager` mode (or equivalent) against `fakeredis`, not real Redis/Postgres — real infra is exercised via `docker compose up -d` manually or in an integration tier if one exists.
- The Celery task itself is a thin wrapper around today's `_run_graph_turn`-equivalent logic using `FakeChatModel`, so existing graph-level test coverage carries over largely unchanged.
- New unit test coverage needed for: the Redis job-hash read/write helper (status transitions, terminal states) and the SSE-relay subscriber (including the already-finished-before-subscribe race).
- Existing webtool/circuit-breaker tests are unaffected.

## Deployment & Rollout

- `backend/docker-compose.yml` gains a `worker` service: same image as the API, different entrypoint (`celery -A agentdrops.worker worker`). No new infra containers — Postgres and Redis are already provisioned.
- New backend dependencies: `celery`, a Redis client, `langgraph-checkpoint-postgres` (+ its driver).
- This is a breaking architecture change (checkpointer backend swap, `/chat` contract change, new required runtime dependency on Redis/Postgres actually being used) — it is not incrementally deployable without discontinuity for in-flight sessions. Any session with a run in progress during cutover loses its `InMemorySaver` state, since Postgres checkpoints start empty. This is an accepted one-time discontinuity, not something the implementation needs to handle gracefully.
