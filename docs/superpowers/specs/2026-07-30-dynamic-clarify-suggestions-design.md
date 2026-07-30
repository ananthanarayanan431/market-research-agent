# Dynamic clarify-question suggestions and idle-state prompts

## Problem

The clarifying-question flow already generates its question text dynamically via
`ClarifyWithUser` (LLM structured output in `agents/scope/graph.py`), but the pill
"suggestion chips" shown under it (`Region: Global`, `Focus: pricing`, ...) are a
hardcoded static array (`frontend/src/lib/mock-data.ts::CLARIFY_CHIPS`) that never
changes regardless of what the actual question asks. Separately, the idle-state
starter prompts shown on a blank chat (`SUGGESTIONS` in the same file) are also
hardcoded. Both should be produced by the LLM instead.

## Part 1: Dynamic clarify chips

Ride the existing `clarify_with_user` LLM call — no new call, just a new field.

- `agents/schemas.py::ClarifyWithUser` — add `suggestions: list[str]`, described as
  2-5 short example answers specific to the question just asked (empty when
  `need_clarification` is false).
- `agents/prompts.py::CLARIFY_PROMPT` — instruct the model to also propose 2-5 short,
  concrete example answers relevant to whatever it asked. Free-form strings, not a
  fixed `Region:`/`Focus:`/`Timeframe:` template — the point is that a question about
  competitors gets competitor-shaped suggestions, a question about region+timeframe
  gets region/timeframe-shaped ones.
- `agents/state.py::AgentState` — add `clarify_suggestions: list[str]`.
- `agents/scope/graph.py::clarify_with_user` — return
  `"clarify_suggestions": result.suggestions if result.need_clarification else []`
  alongside the existing `messages`/`needs_clarification`.
- `service/chat_service.py` — add `"suggestions": node_output.get("clarify_suggestions", [])`
  to the `yield {"type": "clarify", ...}` SSE event.
- `api/v1/chat.py` — update the `chat_stream` docstring's documented event shape.

### Persistence (reload support)

`repository/sessions.py` already persists `clarify_question` per session but it isn't
exposed on `ResearchStatusResponse`, so even the question text is lost on reload today.
Fix both:

- `db/models/sessions.py` — add `clarify_suggestions` column, following the `sources`
  JSONB precedent: `Mapped[list[str]] = mapped_column(JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb"))`.
- New Alembic migration (after `0004_add_sessions_pinned.py`).
- `repository/sessions.py::set_status` — accept and persist `clarify_suggestions`
  alongside the existing `clarify_question` param.
- `api/v1/schema.py::ResearchStatusResponse` — add `clarify_question: str | None` and
  `clarify_suggestions: list[str]`.

### Frontend

- `lib/types.ts` — `StreamEvent`'s `clarify` variant gains `suggestions: string[]`;
  `ResearchStatus` gains `clarify_question`/`clarify_suggestions` for the reload path.
- `app/page.tsx` — lift the latest clarify suggestions into state next to
  `steps`/`sources` (same existing pattern), passed down to `ChatPanel` as a prop.
- `components/app/chat-panel.tsx` — drop the `CLARIFY_CHIPS` import; render chips from
  the prop. Tapping a chip fills the input with that suggestion text (free-form answer,
  not a label:value fragment to append).
- `lib/mock-data.ts` — delete `CLARIFY_CHIPS`.

## Part 2: Dynamic idle-state starter prompts

No user input exists yet at this point, so this needs its own endpoint rather than
riding a chat turn.

- New router `api/v1/suggestions.py` — `GET /v1/suggestions/starter` returns
  `{"prompts": list[str]}` (3 short example research prompts).
- New `agents/schemas.py::StarterSuggestions` — `prompts: list[str]`, structured output
  schema for this call.
- New `service/suggestions_service.py::SuggestionsService` — cache-aside against
  `app.state.redis` (`redis.asyncio.Redis`, already used by `ChatQueueService`):
  - `GET` key `starter_suggestions` → if present, `json.loads` and return.
  - On miss: call the LLM via `agents/llm.py::build_llm` + `ainvoke_with_retry` to
    generate 3 fresh prompts, `SET` into Redis with `ex=3600` (1h TTL), return.
  - Shared across all users — one generation per hour, not per request.
- `main.py` lifespan — construct `SuggestionsService(redis, ...)`, attach to
  `app.state`, mount the new router, same pattern as the other services.

### Frontend

- `lib/api.ts` — add `getStarterSuggestions()` calling `GET /v1/suggestions/starter`.
- `components/app/chat-panel.tsx` — fetch on mount when idle instead of importing the
  static `SUGGESTIONS` array. On fetch error/loading, fall back to today's 3 hardcoded
  strings inline (not re-adding `mock-data.ts`) so the UI never shows an empty state.
- `lib/mock-data.ts` — becomes empty/removed once both chip sources are gone.

## Testing

- Backend: extend existing scope-graph tests for `ClarifyWithUser.suggestions` /
  `clarify_suggestions` state propagation; new `test_suggestions_service.py` covering
  cache-hit, cache-miss+generate, and TTL, using a fake Redis + `FakeChatModel`; route
  tests for `GET /v1/suggestions/starter` and the extended `ResearchStatusResponse`.
- Frontend: no existing test infra for these components — verify manually in-browser
  (clarify chips change per question; idle prompts load from the API; reload of a
  mid-clarification session shows the real question + chips).
