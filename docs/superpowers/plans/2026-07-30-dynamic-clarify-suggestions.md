# Dynamic Clarify Suggestions & Starter Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two hardcoded frontend suggestion arrays (`CLARIFY_CHIPS`, `SUGGESTIONS` in `frontend/src/lib/mock-data.ts`) with LLM-generated content: clarify-question chips that are specific to whatever the model just asked, and starter prompts served from a new cached backend endpoint.

**Architecture:** The clarify chips ride the existing `ClarifyWithUser` structured-output call (one new field, no new LLM call) and flow through the same SSE `clarify` event and session-store persistence that `clarify_question` already uses today. The starter prompts need a standalone `GET /v1/suggestions/starter` endpoint, backed by a new `SuggestionsService` that cache-asides against the already-injected `app.state.redis` (1h TTL) so it's one LLM call per hour, not per page load.

**Tech Stack:** FastAPI, LangGraph, Pydantic structured output, SQLAlchemy + Alembic (Postgres/JSONB), `redis.asyncio`, Next.js/React/TypeScript.

## Global Constraints

- No new provider SDK imports — LLM calls go through `agents/llm.py::build_llm` + `ainvoke_with_retry`, exactly like every existing node (see `CLAUDE.md`).
- SSE event shapes are documented in `api/v1/chat.py::chat_stream`'s docstring and mirrored in `frontend/src/lib/types.ts` — every change to one must update the other in the same task.
- New Postgres columns follow the existing `JSONB` precedent in `db/models/sessions.py` (`sources`, and now `clarify_suggestions`), not `ARRAY`.
- Follow existing test conventions: `tests/unit/agents/conftest.py::make_settings`/`FakeChatModel` for LLM-backed unit tests, `tests/unit/api/v1/conftest.py::client` (real routes, fake graph, `fakeredis`) for route tests — monkeypatch `build_llm` at its *call-site module*, not globally.
- Every step below that runs `pytest` runs it from `backend/`.

---

### Task 1: LLM produces question-specific suggestions alongside the clarifying question

**Files:**
- Modify: `backend/src/agentdrops/agents/schemas.py`
- Modify: `backend/src/agentdrops/agents/prompts.py`
- Modify: `backend/src/agentdrops/agents/state.py`
- Modify: `backend/src/agentdrops/agents/scope/graph.py`
- Test: `backend/tests/unit/agents/scope/test_graph.py`

**Interfaces:**
- Produces: `ClarifyWithUser.suggestions: list[str]`; `AgentState["clarify_suggestions"]: list[str]`; `clarify_with_user(state)` now includes `"clarify_suggestions"` in its returned dict — Task 2 and Task 3 read this key off `node_output`.

- [ ] **Step 1: Write the failing tests**

Replace the two clarify tests in `backend/tests/unit/agents/scope/test_graph.py` (lines 8-38) with:

```python
async def test_clarify_with_user_asks_when_ambiguous(monkeypatch: object) -> None:
    llm = FakeChatModel(
        [
            ClarifyWithUser(
                need_clarification=True,
                question="Which region?",
                verification="",
                suggestions=["North America", "Global", "EU only"],
            )
        ]
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.scope.graph.build_llm", lambda settings, **kw: llm
    )

    clarify_with_user, _ = build_scope_nodes(make_settings())
    result = await clarify_with_user({"messages": [HumanMessage(content="EV charging market")]})

    assert result["needs_clarification"] is True
    assert result["messages"][0].content == "Which region?"
    assert result["clarify_suggestions"] == ["North America", "Global", "EU only"]
    assert route_after_clarify({"needs_clarification": True}) == "__end__"


async def test_clarify_with_user_continues_when_clear(monkeypatch: object) -> None:
    llm = FakeChatModel(
        [
            ClarifyWithUser(
                need_clarification=False, question="", verification="Got it.", suggestions=[]
            )
        ]
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.scope.graph.build_llm", lambda settings, **kw: llm
    )

    clarify_with_user, _ = build_scope_nodes(make_settings())
    result = await clarify_with_user(
        {"messages": [HumanMessage(content="EV charging market in the EU, 2025")]}
    )

    assert result["needs_clarification"] is False
    assert result["clarify_suggestions"] == []
    assert route_after_clarify(result) == "write_research_brief"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/agents/scope/test_graph.py -v`
Expected: FAIL — `ClarifyWithUser(...)` raises a `TypeError`/`ValidationError` for the unexpected `suggestions` kwarg, and/or `KeyError: 'clarify_suggestions'` on the result dict.

- [ ] **Step 3: Implement**

In `backend/src/agentdrops/agents/schemas.py`, add a field to `ClarifyWithUser` (after `verification`, lines 6-15):

```python
class ClarifyWithUser(BaseModel):
    """Whether the chat history has enough detail to research, or needs a clarifying question."""

    need_clarification: bool = Field(
        description="True if the request is too ambiguous to research as-is."
    )
    question: str = Field(description="Clarifying question to ask the user, if needed.")
    verification: str = Field(
        description="Short message confirming scope, used when no clarification is needed."
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="2-5 short, concrete example answers to `question`, specific to what it "
        "actually asks (e.g. example regions/timeframes for a scoping question, example "
        "competitor names for a comparison question). Empty when need_clarification is false.",
    )
```

In `backend/src/agentdrops/agents/prompts.py`, replace `CLARIFY_PROMPT` (lines 11-16):

```python
CLARIFY_PROMPT = """You are the scoping stage of a market-research agent. Today is {date}.

Read the conversation so far. If the request is too ambiguous to research (missing market,
region, timeframe, or comparison target), set need_clarification=true, ask one concise
question, and propose 2-5 short, concrete example answers to that specific question (e.g. if
you asked about region and timeframe, suggest example regions/timeframes; if you asked about
which competitors to include, suggest example competitor names) — they must be answers to the
question you just asked, not a generic fixed list. Otherwise set need_clarification=false,
write a one-line verification of what you understood, and leave suggestions empty."""
```

In `backend/src/agentdrops/agents/state.py`, add a field to `AgentState` (after `needs_clarification`, line 14):

```python
class AgentState(TypedDict):
    """Top-level pipeline state: chat history in, final report out."""

    messages: Annotated[list[AnyMessage], add_messages]
    needs_clarification: bool
    clarify_suggestions: list[str]
    research_brief: str
    supervisor_messages: Annotated[list[AnyMessage], add_messages]
    notes: Annotated[list[str], operator.add]
    final_report: str
```

In `backend/src/agentdrops/agents/scope/graph.py`, update `clarify_with_user` (lines 23-32):

```python
    async def clarify_with_user(state: AgentState) -> dict[str, object]:
        """Ask the model whether the request needs clarification before research starts."""
        system = SystemMessage(content=CLARIFY_PROMPT.format(date=get_today_str()))
        result = await ainvoke_with_retry(clarify_llm, [system, *state["messages"]])
        assert isinstance(result, ClarifyWithUser)
        reply = result.question if result.need_clarification else result.verification
        return {
            "messages": [AIMessage(content=reply)],
            "needs_clarification": result.need_clarification,
            "clarify_suggestions": result.suggestions if result.need_clarification else [],
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/agents/scope/test_graph.py -v`
Expected: PASS (all 4 tests in the file, the two above plus the untouched `write_research_brief` test).

- [ ] **Step 5: Type-check and lint**

Run: `mypy src && ruff check .`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/agents/schemas.py backend/src/agentdrops/agents/prompts.py backend/src/agentdrops/agents/state.py backend/src/agentdrops/agents/scope/graph.py backend/tests/unit/agents/scope/test_graph.py
git commit -m "feat(backend): LLM proposes example answers alongside its clarifying question"
```

---

### Task 2: Persist `clarify_suggestions` and expose both fields for session reload

**Files:**
- Modify: `backend/src/agentdrops/db/models/sessions.py`
- Create: `backend/src/agentdrops/db/migrations/versions/0005_add_sessions_clarify_suggestions.py`
- Modify: `backend/src/agentdrops/repository/sessions.py`
- Modify: `backend/src/agentdrops/api/v1/schema.py`
- Modify: `backend/src/agentdrops/service/research_service.py`
- Modify: `backend/tests/unit/api/v1/conftest.py`
- Test: `backend/tests/unit/repository/test_sessions.py`, `backend/tests/unit/api/v1/test_research.py`

**Interfaces:**
- Produces: `SessionStore.set_status(..., clarify_suggestions: list[str] | None = None)`; `SessionRecord.clarify_suggestions: list[str]`; `ResearchStatusResponse.clarify_question: str | None` and `.clarify_suggestions: list[str]` — Task 3 (SSE event) and Task 4 (frontend reload path) both build on this.

- [ ] **Step 1: Write the failing tests**

Extend `backend/tests/unit/repository/test_sessions.py`'s `test_set_status_stores_clarify_question_and_error` (lines 50-64):

```python
async def test_set_status_stores_clarify_question_suggestions_and_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("t4", title="EV charging in the EU")

    await store.set_status(
        "t4",
        "clarifying",
        clarify_question="Which region?",
        clarify_suggestions=["North America", "Global"],
    )
    clarifying = await store.get("t4")
    assert clarifying is not None
    assert clarifying.clarify_question == "Which region?"
    assert clarifying.clarify_suggestions == ["North America", "Global"]

    await store.set_status("t4", "failed", error="LLM provider unavailable")
    failed = await store.get("t4")
    assert failed is not None
    assert failed.error == "LLM provider unavailable"
```

Add to `backend/tests/unit/api/v1/test_research.py`:

```python
async def test_get_research_status_includes_clarify_question_and_suggestions(
    client: TestClient,
) -> None:
    thread_id = str(uuid.uuid4())
    await _run_turn(client, thread_id, "Research the EV charging market")

    response = client.get(f"/v1/research/{thread_id}")

    data = response.json()["data"]
    assert data["clarify_question"] == "Which region should I focus on?"
    assert data["clarify_suggestions"] == ["North America", "Global", "EU only"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/repository/test_sessions.py tests/unit/api/v1/test_research.py -v`
Expected: `test_set_status_stores_clarify_question_suggestions_and_error` FAILs with `TypeError: set_status() got an unexpected keyword argument 'clarify_suggestions'` (or is skipped if Postgres isn't reachable locally — that's fine, the route test below still catches the wiring). `test_get_research_status_includes_clarify_question_and_suggestions` FAILs with `KeyError: 'clarify_question'`.

- [ ] **Step 3: Implement**

In `backend/src/agentdrops/db/models/sessions.py`, add a column after `clarify_question` (line 21):

```python
    clarify_question: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    clarify_suggestions: Mapped[list[str]] = mapped_column(
        JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
    )
```

Create `backend/src/agentdrops/db/migrations/versions/0005_add_sessions_clarify_suggestions.py`:

```python
# backend/src/agentdrops/db/migrations/versions/0005_add_sessions_clarify_suggestions.py
"""add sessions.clarify_suggestions

Backs the LLM-generated example answers shown alongside a clarifying question
(`SessionStore.set_status(..., clarify_suggestions=...)`), so a reopened mid-clarification
session can show the same chips it showed live.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "clarify_suggestions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "clarify_suggestions")
```

In `backend/src/agentdrops/repository/sessions.py`:

- Add to `SessionRecord` (after `clarify_question`, line 36):
  ```python
      clarify_question: str | None = None
      clarify_suggestions: list[str] = field(default_factory=list)
  ```
- Add to `_to_record` (after `clarify_question=row.clarify_question`, line 49):
  ```python
          clarify_question=row.clarify_question,
          clarify_suggestions=row.clarify_suggestions,
  ```
- Update `set_status` (lines 77-97):
  ```python
      async def set_status(
          self,
          thread_id: str,
          status: Status,
          *,
          report: str | None = None,
          clarify_question: str | None = None,
          clarify_suggestions: list[str] | None = None,
          error: str | None = None,
      ) -> None:
          async with self._session_factory() as session:
              values: dict[str, object] = {"status": status, "updated_at": func.now()}
              if report is not None:
                  values["report"] = report
              if clarify_question is not None:
                  values["clarify_question"] = clarify_question
              if clarify_suggestions is not None:
                  values["clarify_suggestions"] = clarify_suggestions
              if error is not None:
                  values["error"] = error
              await session.execute(
                  update(SessionTable).where(SessionTable.thread_id == thread_id).values(**values)
              )
              await session.commit()
  ```

In `backend/src/agentdrops/api/v1/schema.py`, update `ResearchStatusResponse` (lines 24-30):

```python
class ResearchStatusResponse(BaseModel):
    """Current state of one research thread, read back from the graph's checkpoint."""

    thread_id: str
    status: Literal["queued", "clarifying", "running", "done", "failed"]
    research_brief: str | None = None
    report: str | None = None
    clarify_question: str | None = None
    clarify_suggestions: list[str] = Field(default_factory=list)
```

(Add `Field` to the `pydantic` import at the top of the file: `from pydantic import BaseModel, Field`.)

In `backend/src/agentdrops/service/research_service.py`, update `get_status` (lines 16-44):

```python
    async def get_status(self, thread_id: str) -> ResearchStatusResponse | None:
        """Current state of one research thread: the session store's `failed` if set, else the
        graph's own checkpoint (a failed run may leave an incomplete checkpoint the graph can't
        classify). Returns `None` if `thread_id` is unknown to both."""
        session = await self._sessions.get(thread_id)
        if session is not None and session.status in ("failed", "queued"):
            return ResearchStatusResponse(
                thread_id=thread_id, status=session.status, research_brief=None, report=None
            )

        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        state = await self._graph.aget_state(config)
        if not state.values:
            return None

        values = state.values
        if values.get("final_report"):
            research_status: str = "done"
        elif values.get("needs_clarification"):
            research_status = "clarifying"
        else:
            research_status = "running"

        clarify_question = None
        clarify_suggestions: list[str] = []
        if research_status == "clarifying" and session is not None:
            clarify_question = session.clarify_question
            clarify_suggestions = session.clarify_suggestions

        return ResearchStatusResponse(
            thread_id=thread_id,
            status=research_status,  # type: ignore[arg-type]
            research_brief=values.get("research_brief") or None,
            report=values.get("final_report") or None,
            clarify_question=clarify_question,
            clarify_suggestions=clarify_suggestions,
        )
```

In `backend/tests/unit/api/v1/conftest.py`, update `_FakeSessionStore.set_status` (lines 100-118) to accept and store the new kwarg:

```python
    async def set_status(
        self,
        thread_id: str,
        status: Status,
        *,
        report: str | None = None,
        clarify_question: str | None = None,
        clarify_suggestions: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        session = self._sessions.get(thread_id)
        if session is None:
            return
        session.status = status
        if report is not None:
            session.report = report
        if clarify_question is not None:
            session.clarify_question = clarify_question
        if clarify_suggestions is not None:
            session.clarify_suggestions = clarify_suggestions
        if error is not None:
            session.error = error
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/repository/test_sessions.py tests/unit/api/v1/test_research.py tests/unit/api/v1/test_chat.py -v`
Expected: PASS (repository test auto-skips if the docker-compose Postgres isn't running locally — that's expected/pre-existing behavior, not a regression).

If Postgres *is* reachable, also run the migration against it:

Run: `cd backend && alembic upgrade head`
Expected: applies `0005` cleanly with no errors.

- [ ] **Step 5: Type-check and lint**

Run: `mypy src && ruff check .`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/db/models/sessions.py backend/src/agentdrops/db/migrations/versions/0005_add_sessions_clarify_suggestions.py backend/src/agentdrops/repository/sessions.py backend/src/agentdrops/api/v1/schema.py backend/src/agentdrops/service/research_service.py backend/tests/unit/api/v1/conftest.py backend/tests/unit/repository/test_sessions.py backend/tests/unit/api/v1/test_research.py
git commit -m "feat(backend): persist and expose clarify_question/clarify_suggestions for session reload"
```

---

### Task 3: Stream `suggestions` in the SSE `clarify` event

**Files:**
- Modify: `backend/src/agentdrops/service/chat_service.py`
- Modify: `backend/src/agentdrops/api/v1/chat.py`
- Modify: `backend/tests/unit/api/v1/conftest.py`
- Test: `backend/tests/unit/api/v1/test_chat.py`

**Interfaces:**
- Consumes: `node_output["clarify_suggestions"]` from Task 1; `SessionStore.set_status(..., clarify_suggestions=...)` from Task 2.
- Produces: SSE event `{"type": "clarify", "thread_id": str, "response": str, "suggestions": list[str]}` — Task 4 (frontend) reads this field.

- [ ] **Step 1: Write the failing test**

In `backend/tests/unit/api/v1/conftest.py`, update `_FakeGraph.astream`'s turn-1 branch (lines 38-45) to include suggestions:

```python
        if turn == 1:
            update = {
                "needs_clarification": True,
                "messages": [AIMessage(content="Which region should I focus on?")],
                "clarify_suggestions": ["North America", "Global", "EU only"],
            }
            state.update(update)
            yield ("updates", {"clarify_with_user": update})
            return
```

Add a new test to `backend/tests/unit/api/v1/test_chat.py` (near `test_run_turn_records_audit_row_for_clarify`):

```python
async def test_run_turn_clarify_event_includes_suggestions(client: TestClient) -> None:
    thread_id = str(uuid.uuid4())
    events = []
    service = client.app.state.chat_service
    async for event in service.run_turn(thread_id, "Research the EV charging market", operation="chat"):
        events.append(event)

    clarify_events = [e for e in events if e["type"] == "clarify"]
    assert len(clarify_events) == 1
    assert clarify_events[0]["suggestions"] == ["North America", "Global", "EU only"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/api/v1/test_chat.py::test_run_turn_clarify_event_includes_suggestions -v`
Expected: FAIL with `KeyError: 'suggestions'`.

- [ ] **Step 3: Implement**

In `backend/src/agentdrops/service/chat_service.py`, update the clarify branch (lines 61-77):

```python
                        if node_name == "clarify_with_user" and node_output.get(
                            "needs_clarification"
                        ):
                            question = str(node_output["messages"][-1].content)
                            suggestions = list(node_output.get("clarify_suggestions", []))
                            await self._sessions.set_status(
                                thread_id,
                                "clarifying",
                                clarify_question=question,
                                clarify_suggestions=suggestions,
                            )
                            outcome = "clarify"
                            await self._audit.record(
                                thread_id, operation=operation, status="clarify"
                            )
                            yield {
                                "type": "clarify",
                                "thread_id": thread_id,
                                "response": question,
                                "suggestions": suggestions,
                            }
                            return
```

In `backend/src/agentdrops/api/v1/chat.py`, update the docstring (line 74-75):

```
    - `{"type": "clarify", "thread_id": str, "response": str, "suggestions": list[str]}` —
      terminal: the agent needs more information before it can research; the turn ends here.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/api/v1/test_chat.py -v`
Expected: PASS for all tests in the file, including the new one and the existing `test_run_turn_records_audit_row_for_clarify`.

- [ ] **Step 5: Type-check and lint**

Run: `mypy src && ruff check .`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/service/chat_service.py backend/src/agentdrops/api/v1/chat.py backend/tests/unit/api/v1/conftest.py backend/tests/unit/api/v1/test_chat.py
git commit -m "feat(backend): include LLM-generated suggestions in the clarify SSE event"
```

---

### Task 4: Frontend — clarify chips render the LLM's own suggestions

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/components/app/chat-panel.tsx`
- Modify: `frontend/src/lib/mock-data.ts`

**Interfaces:**
- Consumes: `StreamEvent`'s `clarify.suggestions: string[]` (Task 3) and `ResearchStatus.clarify_suggestions: string[]` (Task 2).
- Produces: `ChatPanel` prop `clarifySuggestions: string[]` / `setClarifySuggestions: (s: string[]) => void`, owned by `page.tsx`.

This task has no backend test cycle to run; verify by running the app (Step 4).

- [ ] **Step 1: Update types**

In `frontend/src/lib/types.ts`, update the `clarify` variant of `StreamEvent` (line 20) and `ResearchStatus` (lines 34-39):

```ts
export type StreamEvent =
  | { type: "progress"; step: string; detail?: string }
  | { type: "source"; topic: string; summary: string }
  | { type: "clarify"; thread_id: string; response: string; suggestions: string[] }
  | { type: "done"; thread_id: string; report: string }
  | { type: "error"; thread_id: string; message: string };

export type ResearchStatusValue = "queued" | "clarifying" | "running" | "done" | "failed";

export type SessionSummary = {
  id: string;
  title: string;
  created_at: string;
  status: ResearchStatusValue;
  pinned: boolean;
};

export type ResearchStatus = {
  thread_id: string;
  status: ResearchStatusValue;
  research_brief: string | null;
  report: string | null;
  clarify_question: string | null;
  clarify_suggestions: string[];
};
```

- [ ] **Step 2: Lift `clarifySuggestions` state into `page.tsx`**

In `frontend/src/app/page.tsx`, add state near the other `useState` calls (after `sources`, line 23):

```ts
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [clarifySuggestions, setClarifySuggestions] = useState<string[]>([]);
```

Clear it in `startRun` (lines 156-165) and `resetAll` (lines 167-179), alongside `setSteps`/`setSources`:

```ts
  const startRun = () => {
    selectionTokenRef.current += 1;
    if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
    setSteps([]);
    setSources([]);
    setClarifySuggestions([]);
    setReport(null);
    setPhase("running");
    setDrawerMode("progress");
    setDrawerOpen(true);
  };

  const resetAll = () => {
    selectionTokenRef.current += 1;
    if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
    setPhase("idle");
    setTopic(null);
    setThreadId(null);
    setSteps([]);
    setSources([]);
    setClarifySuggestions([]);
    setReport(null);
    setMessages([]);
    setDrawerOpen(false);
    setDrawerMode("progress");
  };
```

In `pollUntilSettled` (lines 79-107), set it from the polled status right before recursing:

```ts
        if (status.status === "failed") {
          setPhase("idle");
          return;
        }
        setClarifySuggestions(status.status === "clarifying" ? status.clarify_suggestions : []);
        setPhase(status.status === "clarifying" ? "clarifying" : "running");
        pollUntilSettled(sessionId, token);
```

In `selectSession` (lines 111-154): clear it up front with the other resets (after `setSources([]);`, line 119), and set it from the fetched status right before `pollUntilSettled` is (maybe) called:

```ts
    setTopic(session.title);
    setThreadId(session.id);
    setMessages([]);
    setSteps([]);
    setSources([]);
    setClarifySuggestions([]);
    setReport(null);
    setDrawerOpen(true);
```

```ts
    try {
      const status = await getResearchStatus(session.id);
      if (selectionTokenRef.current !== token) return;
      setDrawerMode("progress");
      setClarifySuggestions(status.status === "clarifying" ? status.clarify_suggestions : []);
      setPhase(status.status === "clarifying" ? "clarifying" : "running");
      if (
        status.status === "clarifying" ||
        status.status === "running" ||
        status.status === "queued"
      ) {
        pollUntilSettled(session.id, token);
      }
    } catch {
      if (selectionTokenRef.current === token) setPhase("idle");
    }
```

Pass the state and setter down to `ChatPanel` (in the JSX around line 193):

```tsx
        <ChatPanel
          phase={phase}
          setPhase={setPhase}
          topic={topic}
          setTopic={setTopic}
          messages={messages}
          addMessage={addMessage}
          sendMessage={sendMessage}
          onStartRun={startRun}
          onOpenDrawer={() => {
            setDrawerMode("progress");
            setDrawerOpen(true);
          }}
          onChooseFormat={(format) => {
            setDrawerMode(format === "paragraph" ? "report" : "table");
            setDrawerOpen(true);
          }}
          clarifySuggestions={clarifySuggestions}
          setClarifySuggestions={setClarifySuggestions}
        />
```

- [ ] **Step 3: `ChatPanel` renders the prop instead of `CLARIFY_CHIPS`**

In `frontend/src/components/app/chat-panel.tsx`:

Drop `CLARIFY_CHIPS` from the mock-data import (line 5):

```ts
import { SUGGESTIONS } from "@/lib/mock-data";
```

Add the two new props to the component signature (lines 9-31):

```tsx
export function ChatPanel({
  phase,
  setPhase,
  topic,
  setTopic,
  messages,
  addMessage,
  sendMessage,
  onStartRun,
  onOpenDrawer,
  onChooseFormat,
  clarifySuggestions,
  setClarifySuggestions,
}: {
  phase: Phase;
  setPhase: (p: Phase) => void;
  topic: string | null;
  setTopic: (t: string) => void;
  messages: Message[];
  addMessage: (m: Message) => void;
  sendMessage: (text: string) => Promise<StreamEvent | null>;
  onStartRun: () => void;
  onOpenDrawer: () => void;
  onChooseFormat: (format: "paragraph" | "table") => void;
  clarifySuggestions: string[];
  setClarifySuggestions: (s: string[]) => void;
}) {
```

Set/clear the prop from the terminal event in `startTopic` (lines 60-77):

```ts
      const event = await sendMessage(text);
      // null means the sidebar switched to a different session before this stream settled —
      // drop the result instead of appending it to whatever session is now on screen.
      if (!event) return;
      if (event.type === "clarify") {
        addMessage({ id: crypto.randomUUID(), kind: "assistant", text: event.response });
        setClarifySuggestions(event.suggestions);
      } else if (event.type === "done") {
        setClarifySuggestions([]);
        addMessage({
          id: crypto.randomUUID(),
          kind: "assistant",
          text: "Research complete. How would you like the findings delivered?",
        });
        setPhase("complete");
      } else if (event.type === "error") {
        setClarifySuggestions([]);
        addMessage({ id: crypto.randomUUID(), kind: "assistant", text: `Research failed: ${event.message}` });
        setPhase("idle");
      }
```

Same for `submitClarify` (lines 104-120):

```ts
      const event = await sendMessage(text);
      if (!event) return;
      if (event.type === "clarify") {
        addMessage({ id: crypto.randomUUID(), kind: "assistant", text: event.response });
        setClarifySuggestions(event.suggestions);
        setPhase("clarifying");
      } else if (event.type === "done") {
        setClarifySuggestions([]);
        addMessage({
          id: crypto.randomUUID(),
          kind: "assistant",
          text: "Research complete. How would you like the findings delivered?",
        });
        setPhase("complete");
      } else if (event.type === "error") {
        addMessage({ id: crypto.randomUUID(), kind: "assistant", text: `Research failed: ${event.message}` });
        setPhase("clarifying");
      }
```

Render the prop instead of the constant (lines 237-254):

```tsx
            {phase === "clarifying" && clarifySuggestions.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {clarifySuggestions.map((chip) => (
                  <button
                    key={chip}
                    onClick={() => toggleChip(chip)}
                    className={cn(
                      "rounded-full border px-3 py-1.5 text-xs transition-colors",
                      selectedChips.includes(chip)
                        ? "border-blue-500 bg-blue-500/10 text-blue-500"
                        : "hover:bg-accent"
                    )}
                  >
                    {chip}
                  </button>
                ))}
              </div>
            )}
```

- [ ] **Step 4: Remove `CLARIFY_CHIPS` from mock data and verify in the browser**

In `frontend/src/lib/mock-data.ts`, delete lines 20-26 (`CLARIFY_CHIPS`).

Run: `cd frontend && npm run lint`
Expected: no errors (confirms no other file still imports `CLARIFY_CHIPS`).

Then start both servers and exercise the golden path in a browser:

Run: `cd backend && uvicorn agentdrops.main:app --reload --port 8000` (and `make worker` per `CLAUDE.md`, and `docker compose up -d`), and separately `cd frontend && npm run dev`.

- Submit an ambiguous research topic (e.g. "AI coding assistants market").
- Confirm the clarifying question shown is model-generated (as today) and the chips underneath are *specific to that question's content*, not the old fixed `Region:`/`Focus:`/`Timeframe:` set.
- Submit a second ambiguous message about a different kind of gap (e.g. one that would prompt a competitor-set question) and confirm the chips change to match.
- Reload the page mid-clarification (or reopen the session from the sidebar) and confirm the same question + chips reappear instead of a blank state.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/app/page.tsx frontend/src/components/app/chat-panel.tsx frontend/src/lib/mock-data.ts
git commit -m "feat(frontend): render clarify chips from the LLM's own suggestions"
```

---

### Task 5: Backend — cached `GET /v1/suggestions/starter` endpoint

**Files:**
- Modify: `backend/src/agentdrops/agents/schemas.py`
- Modify: `backend/src/agentdrops/agents/prompts.py`
- Create: `backend/src/agentdrops/service/suggestions_service.py`
- Create: `backend/src/agentdrops/api/v1/suggestions.py`
- Modify: `backend/src/agentdrops/api/v1/schema.py`
- Modify: `backend/src/agentdrops/api/v1/__init__.py`
- Modify: `backend/src/agentdrops/main.py`
- Test: `backend/tests/unit/service/test_suggestions_service.py` (new)
- Test: `backend/tests/unit/api/v1/test_suggestions.py` (new)

**Interfaces:**
- Produces: `SuggestionsService.get_starter_prompts() -> list[str]`; `GET /v1/suggestions/starter` returning `SuccessResponse[StarterSuggestionsResponse]` where `StarterSuggestionsResponse.prompts: list[str]` — Task 6 (frontend) calls this route.

- [ ] **Step 1: Write the failing service test**

Create `backend/tests/unit/service/test_suggestions_service.py`:

```python
import json

from fakeredis.aioredis import FakeRedis

from agentdrops.agents.schemas import StarterSuggestions
from agentdrops.service.suggestions_service import _CACHE_KEY, SuggestionsService
from tests.unit.agents.conftest import FakeChatModel, make_settings


async def test_get_starter_prompts_calls_llm_on_cache_miss_and_caches_result(
    monkeypatch: object,
) -> None:
    llm = FakeChatModel([StarterSuggestions(prompts=["A", "B", "C"])])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.service.suggestions_service.build_llm", lambda settings, **kw: llm
    )
    redis = FakeRedis(decode_responses=True)
    service = SuggestionsService(make_settings(), redis)

    prompts = await service.get_starter_prompts()

    assert prompts == ["A", "B", "C"]
    assert json.loads(await redis.get(_CACHE_KEY)) == ["A", "B", "C"]


async def test_get_starter_prompts_returns_cached_value_without_calling_llm(
    monkeypatch: object,
) -> None:
    def _fail(*_a: object, **_kw: object) -> None:
        raise AssertionError("build_llm should not be called on a cache hit")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.service.suggestions_service.build_llm", _fail
    )
    redis = FakeRedis(decode_responses=True)
    await redis.set(_CACHE_KEY, json.dumps(["Cached A", "Cached B"]))
    service = SuggestionsService(make_settings(), redis)

    prompts = await service.get_starter_prompts()

    assert prompts == ["Cached A", "Cached B"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/service/test_suggestions_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.service.suggestions_service'`.

- [ ] **Step 3: Implement the schema, prompt, and service**

In `backend/src/agentdrops/agents/schemas.py`, add a new schema at the end of the file:

```python
class StarterSuggestions(BaseModel):
    """Example research prompts shown on the idle chat state, before the user has typed anything."""

    prompts: list[str] = Field(
        description="3 short, varied example market-research prompts a user might submit — "
        "different industries/markets each time, one sentence each."
    )
```

In `backend/src/agentdrops/agents/prompts.py`, add a new prompt template at the end of the file:

```python
STARTER_SUGGESTIONS_PROMPT = """You are generating example prompts for a market-research
agent's idle chat screen. Today is {date}.

Propose 3 short, varied example research requests a user might submit — different
industries/markets each time (e.g. one tech, one consumer goods, one industrial/other), each
one sentence, phrased the way a user would actually type it."""
```

Create `backend/src/agentdrops/service/suggestions_service.py`:

```python
"""Suggestions service: LLM-generated example research prompts for the idle chat state, cached
in Redis so repeat page loads don't each trigger a fresh LLM call.
"""

import json

from langchain_core.messages import SystemMessage
from redis.asyncio import Redis

from agentdrops.agents.llm import ainvoke_with_retry, build_llm
from agentdrops.agents.prompts import STARTER_SUGGESTIONS_PROMPT, get_today_str
from agentdrops.agents.schemas import StarterSuggestions
from agentdrops.config import Settings

_CACHE_KEY = "starter_suggestions"
_CACHE_TTL_SECONDS = 3600


class SuggestionsService:
    """Generates example research prompts for the idle chat state via the LLM, cache-asided
    against Redis for `_CACHE_TTL_SECONDS` — shared across every user, one LLM call per hour
    rather than one per page load."""

    def __init__(self, settings: Settings, redis: Redis) -> None:
        self._settings = settings
        self._redis = redis

    async def get_starter_prompts(self) -> list[str]:
        cached = await self._redis.get(_CACHE_KEY)
        if cached is not None:
            result: list[str] = json.loads(cached)
            return result

        llm = build_llm(self._settings, temperature=0.7).with_structured_output(
            StarterSuggestions
        )
        system = SystemMessage(content=STARTER_SUGGESTIONS_PROMPT.format(date=get_today_str()))
        result = await ainvoke_with_retry(llm, [system])
        assert isinstance(result, StarterSuggestions)

        await self._redis.set(_CACHE_KEY, json.dumps(result.prompts), ex=_CACHE_TTL_SECONDS)
        return result.prompts
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/service/test_suggestions_service.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing route test**

Create `backend/tests/unit/api/v1/test_suggestions.py`:

```python
import pytest
from fastapi.testclient import TestClient

import agentdrops.service.suggestions_service as suggestions_service_module
from agentdrops.agents.schemas import StarterSuggestions
from tests.unit.agents.conftest import FakeChatModel


async def test_get_starter_suggestions_returns_llm_generated_prompts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeChatModel([StarterSuggestions(prompts=["A", "B", "C"])])
    monkeypatch.setattr(suggestions_service_module, "build_llm", lambda settings, **kw: llm)

    response = client.get("/v1/suggestions/starter")

    assert response.status_code == 200
    assert response.json()["data"]["prompts"] == ["A", "B", "C"]


async def test_get_starter_suggestions_uses_cache_on_second_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = 0

    def _build_llm(settings: object, **kw: object) -> FakeChatModel:
        nonlocal call_count
        call_count += 1
        return FakeChatModel([StarterSuggestions(prompts=["A", "B", "C"])])

    monkeypatch.setattr(suggestions_service_module, "build_llm", _build_llm)

    first = client.get("/v1/suggestions/starter")
    second = client.get("/v1/suggestions/starter")

    assert first.status_code == 200
    assert second.status_code == 200
    assert call_count == 1
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `pytest tests/unit/api/v1/test_suggestions.py -v`
Expected: FAIL — `404 Not Found` (no such route yet) or `AttributeError: 'State' object has no attribute 'suggestions_service'`.

- [ ] **Step 7: Implement the route and wire it up**

In `backend/src/agentdrops/api/v1/schema.py`, add a response model (near `SessionsResponse`):

```python
class StarterSuggestionsResponse(BaseModel):
    """Example research prompts for the idle chat state."""

    prompts: list[str]
```

Create `backend/src/agentdrops/api/v1/suggestions.py`:

```python
"""Starter-suggestion endpoint: LLM-generated example research prompts for the idle chat state."""

from fastapi import APIRouter, Request, status

from agentdrops.api.v1.schema import StarterSuggestionsResponse
from agentdrops.service.suggestions_service import SuggestionsService
from agentdrops.types.response import SuccessResponse

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


@router.get(
    "/starter",
    response_model=SuccessResponse[StarterSuggestionsResponse],
    status_code=status.HTTP_200_OK,
    summary="Get example research prompts for the idle chat state",
)
async def get_starter_suggestions(
    request: Request,
) -> SuccessResponse[StarterSuggestionsResponse]:
    """LLM-generated example prompts shown before the user has typed anything, cached for an
    hour so this isn't a fresh LLM call on every page load."""
    service: SuggestionsService = request.app.state.suggestions_service
    prompts = await service.get_starter_prompts()
    return SuccessResponse(data=StarterSuggestionsResponse(prompts=prompts))
```

In `backend/src/agentdrops/api/v1/__init__.py`, mount the new router:

```python
"""v1 HTTP surface: chat + research routers, mounted under `/v1`."""

from fastapi import APIRouter

from agentdrops.api.v1.chat import router as chat_router
from agentdrops.api.v1.research import router as research_router
from agentdrops.api.v1.sessions import router as sessions_router
from agentdrops.api.v1.suggestions import router as suggestions_router

router = APIRouter(prefix="/v1")
router.include_router(chat_router)
# sessions_router before research_router: both mount under /research, and the static
# /research/sessions route must be matched before research_router's dynamic /research/{thread_id}.
router.include_router(sessions_router)
router.include_router(research_router)
router.include_router(suggestions_router)

__all__ = ["router"]
```

In `backend/src/agentdrops/main.py`, construct and attach the service in `lifespan` (after `app.state.sessions_service = SessionsService(sessions)`, line 66), and import it:

```python
from agentdrops.service.sessions_service import SessionsService
from agentdrops.service.suggestions_service import SuggestionsService
```

```python
                app.state.sessions_service = SessionsService(sessions)
                app.state.suggestions_service = SuggestionsService(settings, redis)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `pytest tests/unit/api/v1/test_suggestions.py tests/unit/service/test_suggestions_service.py -v`
Expected: PASS.

Run the full backend suite to confirm nothing else broke:

Run: `pytest`
Expected: all tests PASS.

- [ ] **Step 9: Type-check and lint**

Run: `mypy src && ruff check .`
Expected: no new errors.

- [ ] **Step 10: Commit**

```bash
git add backend/src/agentdrops/agents/schemas.py backend/src/agentdrops/agents/prompts.py backend/src/agentdrops/service/suggestions_service.py backend/src/agentdrops/api/v1/suggestions.py backend/src/agentdrops/api/v1/schema.py backend/src/agentdrops/api/v1/__init__.py backend/src/agentdrops/main.py backend/tests/unit/service/test_suggestions_service.py backend/tests/unit/api/v1/test_suggestions.py
git commit -m "feat(backend): add cached GET /v1/suggestions/starter endpoint"
```

---

### Task 6: Frontend — idle-state prompts fetched from the backend

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/components/app/chat-panel.tsx`
- Modify: `frontend/src/lib/mock-data.ts`

**Interfaces:**
- Consumes: `GET /v1/suggestions/starter` (Task 5).
- Produces: `api.ts::getStarterSuggestions(): Promise<string[]>`.

No backend test cycle; verify by running the app (Step 3).

- [ ] **Step 1: Add the API call**

In `frontend/src/lib/api.ts`, add near the other `GET` helpers (after `getResearchReport`):

```ts
/** Fetch LLM-generated example research prompts for the idle chat state, cached server-side. */
export async function getStarterSuggestions(): Promise<string[]> {
  const response = await fetch(`${API_BASE_URL}/v1/suggestions/starter`);
  const { prompts } = await unwrap<{ prompts: string[] }>(response);
  return prompts;
}
```

- [ ] **Step 2: `ChatPanel` fetches on mount instead of importing `SUGGESTIONS`**

In `frontend/src/components/app/chat-panel.tsx`:

Update imports (line 1-7):

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, CheckCircle2, Loader2, Sparkles } from "lucide-react";
import { getStarterSuggestions } from "@/lib/api";
import { Message, Phase, StreamEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

const FALLBACK_STARTER_SUGGESTIONS = [
  "Competitive landscape for enterprise SaaS in fintech",
  "Consumer trends in plant-based foods, US market",
  "Market sizing for AI coding assistants",
];
```

Add state and a fetch-on-mount effect (after the existing `useEffect` that scrolls to `bottomRef`, around line 42):

```ts
  const [starterSuggestions, setStarterSuggestions] = useState<string[]>(
    FALLBACK_STARTER_SUGGESTIONS
  );

  useEffect(() => {
    let cancelled = false;
    getStarterSuggestions()
      .then((prompts) => {
        if (!cancelled && prompts.length > 0) setStarterSuggestions(prompts);
      })
      .catch(() => {
        // Keep the fallback list — the idle screen must never show nothing.
      });
    return () => {
      cancelled = true;
    };
  }, []);
```

Render the state instead of the constant (line 172-182, `SUGGESTIONS.map` → `starterSuggestions.map`):

```tsx
            <div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-3">
              {starterSuggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => startTopic(s)}
                  className="rounded-lg border p-4 text-left text-sm transition-colors hover:border-blue-500/40 hover:bg-accent"
                >
                  {s}
                </button>
              ))}
            </div>
```

- [ ] **Step 3: Remove the now-unused mock data and verify in the browser**

In `frontend/src/lib/mock-data.ts`, delete lines 14-18 (`SUGGESTIONS`).

Run: `cd frontend && npm run lint`
Expected: no errors.

With both servers running (per Task 4 Step 4):

- Load the app fresh (empty chat). Confirm 3 starter prompts render — first load may briefly show the fallback 3 before the fetch resolves, then may swap to LLM-generated ones.
- Reload again within an hour; confirm the same LLM-generated prompts reappear (served from the Redis cache, not a fresh generation) — check the backend log for exactly one LLM call across both loads.
- Click a starter prompt and confirm it still starts a research turn normally.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/components/app/chat-panel.tsx frontend/src/lib/mock-data.ts
git commit -m "feat(frontend): fetch idle-state starter prompts from the backend"
```
