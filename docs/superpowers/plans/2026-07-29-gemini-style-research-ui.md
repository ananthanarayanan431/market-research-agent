# Gemini-style Research Drawer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream per-URL sources out of the research sub-agent, and use them (plus richer
per-step text) to give the research drawer's progress view a Gemini-style live narrative with
skeleton loading, render the final report as real markdown, and align a few chrome details
(header export menu, chat topic-card timestamp).

**Architecture:** Backend: `run_search_pipeline` emits one custom `source_url` write per deduped
search result; `run_topic` in the supervisor graph switches its nested research-subgraph call
from `ainvoke` to `astream(stream_mode=["custom","values"])` so those writes actually reach the
`/chat/stream` consumer (the same fix already applied one level up for the supervisor subgraph
itself), tagging each with the delegated topic before relaying. Frontend: a new merged
`timeline` array in `page.tsx` (steps + coalesced source-url groups + per-topic summaries, in
arrival order) replaces the old separate step-checklist + end-of-list source block in
`ProgressView`; `ReportView` switches to real markdown rendering; two small chrome tweaks
(header export menu, topic-card timestamp) round it out.

**Tech Stack:** Python 3.12 / FastAPI / LangGraph (backend), Next.js 16 / React 19 / TypeScript /
Tailwind v4 (frontend), pytest (backend tests), no frontend test suite (verify via
`npm run lint` + `npm run build` + manual browser check).

## Global Constraints

- Backend tests run via `pytest` from `backend/` (asyncio_mode=auto, pythonpath=src — no manual
  PYTHONPATH); also run `ruff check .` and `mypy src` (strict mode) from `backend/` before
  committing backend changes.
- Frontend checks run via `npm run lint` and `npm run build` from `frontend/`.
- SSE event shapes are documented in `backend/src/agentdrops/api/v1/chat.py`'s `chat_stream`
  docstring **and** mirrored in `frontend/src/lib/types.ts` — both change together (existing
  CLAUDE.md rule).
- No new nested-`ainvoke`-of-a-subgraph pattern: any subgraph whose nodes call
  `get_stream_writer()` must be drained via `astream(stream_mode=["custom", "values"])` with
  `"custom"` chunks relayed through the caller's own writer, exactly as `agents/graph.py`'s
  `supervisor` node and (after this plan) `supervisor/graph.py`'s `run_topic` do.
- No new frontend UI library (no Radix/shadcn menu primitive) — the header export menu is
  hand-rolled with `useState`, consistent with this repo not having one yet.
- Only one new frontend dependency: `react-markdown`. No `@tailwindcss/typography`.
- Favicon icons are fetched client-side from `https://www.google.com/s2/favicons?domain=...`
  (Google's public favicon service) — no backend involvement, no local favicon storage.
- No change to the `/v1/chat/stream` terminal event contract (`clarify`/`done`/`error`) or to
  session persistence (`repository/sessions.py`, migrations).
- Create a new git commit per task (never amend); never use `--no-verify`.

---

### Task 1: Backend — emit `source_url` per deduped search result

**Files:**
- Modify: `backend/src/agentdrops/agents/research/methods.py`
- Test: `backend/tests/unit/agents/research/test_methods.py`

**Interfaces:**
- Consumes: `SearchResult` (`backend/src/agentdrops/webtools/base.py`) — `tool_name: str`,
  `title: str`, `url: str` fields already exist, unchanged.
- Produces: `run_search_pipeline` (signature unchanged: `(search_tool, llm, query, max_results)
  -> str`) now also emits, via `get_stream_writer()`, one custom write per deduped result shaped
  `{"type": "source_url", "tool_name": str, "title": str, "url": str}`, in dedup order, before
  summarization is awaited. Later tasks (Task 2) merge a `"topic"` key into this dict before
  relaying it further — `run_search_pipeline` itself has no `topic` in scope and must not try to
  add one.

- [ ] **Step 1: Write the failing tests**

`get_stream_writer()` raises `RuntimeError("Called get_config outside of a runnable context")`
when called outside any LangGraph run — confirmed by running it standalone against this repo's
installed `langgraph`. Both the new test and the existing `test_run_search_pipeline_dedupes_and_formats`
(which calls `run_search_pipeline` directly, not inside a graph) must stub it out.

In `backend/tests/unit/agents/research/test_methods.py`, update the existing test and add a new
one:

```python
async def test_run_search_pipeline_dedupes_and_formats(monkeypatch: object) -> None:
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.research.methods.get_stream_writer", lambda: lambda _payload: None
    )

    class _FakeTool:
        name = "fake"

        async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
            return [_result("https://a.com"), _result("https://a.com")]

    llm = FakeChatModel([Summary(summary="only once", key_excerpts="")])

    output = await run_search_pipeline(_FakeTool(), llm, "query", 5)  # type: ignore[arg-type]

    assert output.count("SOURCE") == 1
    assert "only once" in output


async def test_run_search_pipeline_emits_source_url_per_deduped_result(monkeypatch: object) -> None:
    class _FakeTool:
        name = "fake"

        async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
            return [
                _result("https://a.com", title="A"),
                _result("https://a.com", title="A dup"),
                _result("https://b.com", title="B"),
            ]

    writes: list[dict[str, str]] = []
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.research.methods.get_stream_writer", lambda: writes.append
    )
    llm = FakeChatModel(
        [Summary(summary="s1", key_excerpts=""), Summary(summary="s2", key_excerpts="")]
    )

    await run_search_pipeline(_FakeTool(), llm, "query", 5)  # type: ignore[arg-type]

    assert writes == [
        {"type": "source_url", "tool_name": "tavily", "title": "A", "url": "https://a.com"},
        {"type": "source_url", "tool_name": "tavily", "title": "B", "url": "https://b.com"},
    ]
```

(`_result(...)` already exists at the top of this file and defaults `tool_name="tavily"`.)
Replace the old `test_run_search_pipeline_dedupes_and_formats` definition in place with the
`monkeypatch`-taking version above; add the new test after it.

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/unit/agents/research/test_methods.py -v`

Expected: both `test_run_search_pipeline_dedupes_and_formats` and
`test_run_search_pipeline_emits_source_url_per_deduped_result` fail with `AttributeError:
<module 'agentdrops.agents.research.methods'> does not have the attribute 'get_stream_writer'`
— `get_stream_writer` isn't imported into `methods.py` yet, so `monkeypatch.setattr` can't find
it. The other tests in the file (which don't call `run_search_pipeline`) still pass.

- [ ] **Step 3: Implement**

In `backend/src/agentdrops/agents/research/methods.py`, add the import and the emit loop:

```python
from langgraph.config import get_stream_writer
```

(add alongside the existing `langchain_core.language_models` import at the top)

In `run_search_pipeline`, right after `deduped = deduplicate_search_results(results)` (and its
two `span.set_attribute` lines), insert:

```python
        writer = get_stream_writer()
        for result in deduped:
            writer(
                {"type": "source_url", "tool_name": result.tool_name, "title": result.title, "url": result.url}
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/agents/research/test_methods.py -v`
Expected: all tests in the file PASS.

- [ ] **Step 5: Run repo-wide checks**

Run (from `backend/`): `pytest`, `ruff check .`, `mypy src`
Expected: all pass — no other test calls `run_search_pipeline` outside a graph context.

- [ ] **Step 6: Commit**

```bash
cd backend
git add src/agentdrops/agents/research/methods.py tests/unit/agents/research/test_methods.py
git commit -m "$(cat <<'EOF'
feat(backend): stream one source_url event per deduped search result

EOF
)"
```

---

### Task 2: Backend — relay `source_url` (and other custom writes) out of the research subgraph

**Files:**
- Modify: `backend/src/agentdrops/agents/supervisor/graph.py`
- Modify: `backend/src/agentdrops/api/v1/chat.py`
- Test: `backend/tests/unit/agents/supervisor/test_graph.py`

**Interfaces:**
- Consumes: the `source_url` writes from Task 1 (shape `{"type": "source_url", "tool_name": str,
  "title": str, "url": str}`, no `topic` key).
- Produces: on the wire (via `/v1/chat/stream`), a new terminal-adjacent event shape:
  `{"type": "source_url", "tool_name": str, "title": str, "url": str, "topic": str}` — `topic`
  merged in by `run_topic`. Existing `progress`/`source` event shapes are unchanged. Frontend
  Task 3 consumes this exact shape.

- [ ] **Step 1: Write the failing test**

In `backend/tests/unit/agents/supervisor/test_graph.py`, replace `_FakeResearchGraph` (it
currently only implements `.ainvoke()`, which `run_topic` will no longer call) with a version
implementing `.astream()`, simulating one `source_url` custom write followed by the final state:

```python
class _FakeResearchGraph:
    """Stub research subgraph: streams one fake source_url write (simulating what
    `run_search_pipeline` emits), then yields the final compressed-research state."""

    async def astream(self, state: dict, stream_mode: list[str]):
        topic = state["research_topic"]
        yield (
            "custom",
            {
                "type": "source_url",
                "tool_name": "tavily",
                "title": f"Result for {topic}",
                "url": f"https://example.com/{topic}",
            },
        )
        yield ("values", {"compressed_research": f"findings on {topic}"})
```

Add a new test after the existing ones:

```python
async def test_run_topic_relays_source_url_events_with_topic(monkeypatch: object) -> None:
    delegate = AIMessage(
        content="",
        tool_calls=[
            {"name": "ConductResearch", "args": {"research_topic": "topic A"}, "id": "call-1"}
        ],
    )
    complete = AIMessage(
        content="", tool_calls=[{"name": "ResearchComplete", "args": {}, "id": "call-2"}]
    )
    stop = AIMessage(content="Research is complete, wrapping up.")
    llm = FakeChatModel([delegate, complete, stop])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.supervisor.graph.build_llm", lambda settings, **kw: llm
    )

    settings = make_settings(max_researcher_iterations=5)
    graph = build_supervisor_graph(settings, _FakeResearchGraph())  # type: ignore[arg-type]

    customs: list[dict[str, str]] = []
    async for stream_type, chunk in graph.astream(
        {"supervisor_messages": [], "research_brief": "EV charging", "research_iterations": 0},
        stream_mode=["custom", "values"],
    ):
        if stream_type == "custom":
            customs.append(chunk)

    assert {
        "type": "source_url",
        "tool_name": "tavily",
        "title": "Result for topic A",
        "url": "https://example.com/topic A",
        "topic": "topic A",
    } in customs
```

This calls `build_supervisor_graph(...)`'s own `.astream(stream_mode=["custom", "values"])`
directly — the same way `agents/graph.py`'s `supervisor` node drives it in production — so it
actually proves the relay reaches a real `"custom"` consumer, unlike calling `.ainvoke()` (which
would pass even if the relay were broken, since dropped custom writes don't raise).

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/unit/agents/supervisor/test_graph.py -v`

Expected: `test_run_topic_relays_source_url_events_with_topic` fails (assertion error — no
`source_url` chunk relayed yet, since `run_topic` still calls `.ainvoke()` and never reads
`.astream()`'s custom stream). `test_supervisor_fans_out_conduct_research_and_completes` and
`test_supervisor_stops_at_iteration_cap` fail too, with `AttributeError: '_FakeResearchGraph'
object has no attribute 'ainvoke'` — expected, since the fake no longer implements it; this
resolves once Step 3 updates `run_topic` to call `.astream()` instead.

- [ ] **Step 3: Implement**

In `backend/src/agentdrops/agents/supervisor/graph.py`:

Update imports at the top:

```python
from typing import Any, cast
```

```python
from agentdrops.agents.state import ResearcherState, SupervisorState
```

Replace `run_topic` with:

```python
    async def run_topic(call: ToolCall) -> ToolMessage:
        """Run the research sub-agent on one delegated topic, bounded by the concurrency cap.

        Streamed via `astream` (not `ainvoke`) and re-emitted through this function's own
        writer: a bare nested `ainvoke()` starts an isolated run whose `custom` writes (the
        `source_url` events `run_search_pipeline` emits) would otherwise never reach the outer
        `/chat/stream` consumer — the same reason the top-level `supervisor` node in
        `agents/graph.py` streams the supervisor subgraph instead of invoking it directly.
        """
        writer = get_stream_writer()
        topic = call["args"]["research_topic"]
        async with semaphore:
            writer({"type": "progress", "step": "researching", "detail": f"Researching: {topic}"})
            final_state: ResearcherState | None = None
            async for stream_type, chunk in research_graph.astream(
                {
                    "researcher_messages": [],
                    "research_topic": topic,
                    "tool_call_iterations": 0,
                    "compressed_research": "",
                },
                stream_mode=["custom", "values"],
            ):
                if stream_type == "custom":
                    writer({**chunk, "topic": topic})
                else:
                    final_state = cast(ResearcherState, chunk)
            assert final_state is not None
        writer(
            {
                "type": "source",
                "topic": topic,
                "summary": final_state["compressed_research"][:280],
            }
        )
        return ToolMessage(
            content=final_state["compressed_research"],
            tool_call_id=call["id"],
            name="ConductResearch",
        )
```

In `backend/src/agentdrops/api/v1/chat.py`, add a line to the `chat_stream` docstring's event
list, right after the existing `source` line:

```python
    - `{"type": "source_url", "topic": str, "tool_name": str, "title": str, "url": str}` — one
      individual search result was found while researching a delegated topic.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/agents/supervisor/test_graph.py -v`
Expected: all four tests PASS.

- [ ] **Step 5: Run repo-wide checks**

Run (from `backend/`): `pytest`, `ruff check .`, `mypy src`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd backend
git add src/agentdrops/agents/supervisor/graph.py src/agentdrops/api/v1/chat.py tests/unit/agents/supervisor/test_graph.py
git commit -m "$(cat <<'EOF'
fix(backend): relay source_url writes out of the research subgraph via astream

EOF
)"
```

---

### Task 3: Frontend — merged progress timeline with skeleton loading

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Create: `frontend/src/components/ui/skeleton.tsx`
- Modify: `frontend/src/components/app/research-drawer.tsx`
- Modify: `frontend/src/app/page.tsx`

**Interfaces:**
- Consumes: the `source_url` wire event from Task 2 (`{type:"source_url", topic, tool_name,
  title, url}`).
- Produces: `TimelineEntry` (exported from `research-drawer.tsx`):
  ```ts
  export type TimelineEntry =
    | { kind: "step"; title: string; detail?: string }
    | { kind: "sourceGroup"; topic: string; toolName: string; items: { title: string; url: string }[] }
    | { kind: "sourceSummary"; topic: string; summary: string };
  ```
  `ResearchDrawer` takes a new `timeline: TimelineEntry[]` prop (replacing `steps:
  ProgressStep[]` — `ProgressStep` had no other consumer, so it is deleted from `lib/types.ts`).
  `Skeleton` (from `ui/skeleton.tsx`): `{ className?: string }`. Task 5 reuses `TimelineEntry`'s
  `"progress"|"table"` mode check pattern already in this file; Task 4/5 don't touch this task's
  types.

No automated frontend tests exist in this repo; verification is `npm run lint`, `npm run build`,
and a manual browser check (steps below).

- [ ] **Step 1: Add the `source_url` wire type**

In `frontend/src/lib/types.ts`, delete the `ProgressStep` type (lines 7-10) — it becomes unused
once this task lands. Add a new variant to `StreamEvent`:

```ts
export type StreamEvent =
  | { type: "progress"; step: string; detail?: string }
  | { type: "source"; topic: string; summary: string }
  | { type: "source_url"; topic: string; tool_name: string; title: string; url: string }
  | { type: "clarify"; thread_id: string; response: string }
  | { type: "done"; thread_id: string; report: string }
  | { type: "error"; thread_id: string; message: string };
```

- [ ] **Step 2: Add the `Skeleton` primitive**

Create `frontend/src/components/ui/skeleton.tsx`:

```tsx
import { cn } from "@/lib/utils";

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("bg-accent animate-pulse rounded-md", className)}
      {...props}
    />
  );
}

export { Skeleton };
```

- [ ] **Step 3: Rewrite `ProgressView` in `research-drawer.tsx` to use a `timeline`**

Update the top-of-file imports:

```tsx
import { CheckCircle2, Circle, Loader2, Sparkles, X } from "lucide-react";
import { ResearchSource } from "@/lib/types";
import { Skeleton } from "@/components/ui/skeleton";
```

**Note:** in a clean checkout `CheckCircle2` would become unused here (the old step-done icon it
served is replaced by `Sparkles`) and should be dropped. But concurrent work already in this
file (a teammate's uncommitted sessions-pinning branch) also uses `CheckCircle2` for the header's
running/done status icon, unrelated to `ProgressView` — keep it. Before editing, confirm by
checking the current file for other `CheckCircle2` usages beyond the old `ProgressView`; only
drop it from the import if none remain. `ProgressStep` is removed from this import since Step 1
deletes it from `lib/types.ts`.

Add the exported `TimelineEntry` type near the top of the file, right after `DrawerMode`:

```tsx
export type TimelineEntry =
  | { kind: "step"; title: string; detail?: string }
  | { kind: "sourceGroup"; topic: string; toolName: string; items: { title: string; url: string }[] }
  | { kind: "sourceSummary"; topic: string; summary: string };
```

Update `ResearchDrawer`'s props: replace `steps: ProgressStep[]` with `timeline:
TimelineEntry[]` in both the destructured parameter list and its type, and pass `timeline`
instead of `steps` into `<ProgressView .../>`:

```tsx
        {mode === "progress" && (
          <ProgressView timeline={timeline} isRunning={isRunning} />
        )}
```

Replace the whole `ProgressView` function with:

```tsx
function faviconUrl(url: string): string {
  try {
    return `https://www.google.com/s2/favicons?domain=${new URL(url).hostname}`;
  } catch {
    return "";
  }
}

function ProgressSkeleton() {
  return (
    <div className="space-y-6">
      {[0, 1, 2, 3].map((group) => (
        <div key={group} className="space-y-2 border-l-2 pl-4">
          <Skeleton className="h-3.5 w-2/3" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
        </div>
      ))}
    </div>
  );
}

function ProgressView({
  timeline,
  isRunning,
}: {
  timeline: TimelineEntry[];
  isRunning: boolean;
}) {
  if (timeline.length === 0) {
    return isRunning ? (
      <ProgressSkeleton />
    ) : (
      <div className="flex gap-2">
        <Circle className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground/40" />
        <div className="text-sm text-muted-foreground">Waiting to start...</div>
      </div>
    );
  }

  return (
    <ul className="space-y-5">
      {timeline.map((entry, i) => {
        if (entry.kind === "step") {
          const isLast = i === timeline.length - 1;
          return (
            <li key={`step-${i}`} className="flex gap-2">
              <div className="mt-1 shrink-0">
                {isLast && isRunning ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5 text-blue-500" />
                )}
              </div>
              <div>
                <div className="text-sm font-medium italic text-foreground">{entry.title}</div>
                {entry.detail && (
                  <div className="mt-1 text-xs text-muted-foreground">{entry.detail}</div>
                )}
              </div>
            </li>
          );
        }
        if (entry.kind === "sourceGroup") {
          return (
            <li key={`group-${i}`} className="pl-6">
              <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {entry.toolName}
              </div>
              <div className="grid grid-cols-3 gap-2">
                {entry.items.map((item, j) => (
                  <a
                    key={`${item.url}-${j}`}
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-1.5 truncate rounded-md border p-1.5 text-[11px] hover:bg-accent"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element -- small third-party favicon, not worth next/image config */}
                    <img
                      src={faviconUrl(item.url)}
                      alt=""
                      className="h-3.5 w-3.5 shrink-0 rounded-sm"
                    />
                    <span className="truncate">{item.title}</span>
                  </a>
                ))}
              </div>
            </li>
          );
        }
        return (
          <li key={`summary-${i}`} className="pl-6">
            <div className="rounded-md border p-2">
              <div className="truncate text-xs font-medium">{entry.topic}</div>
              <div className="truncate text-[11px] text-muted-foreground">{entry.summary}</div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
```

`sources: ResearchSource[]` is still used by `TableViewMode` and `ReportView`'s `sourceCount` —
leave `ResearchDrawer`'s `sources` prop, and those two functions, untouched in this task.

- [ ] **Step 4: Build the timeline in `page.tsx`**

Update the type import:

```tsx
import { DrawerMode, ResearchDrawer, TimelineEntry } from "@/components/app/research-drawer";
```

```tsx
import {
  Message,
  Phase,
  ResearchSource,
  SessionSummary,
  StreamEvent,
} from "@/lib/types";
```

(`ProgressStep` removed — deleted from `lib/types.ts` in Step 1.)

Replace the `steps` state declaration:

```tsx
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
```

In `sendMessage`'s `streamChat` callback, replace the `progress`/`source` branches and add
`source_url`:

```tsx
        await streamChat(text, threadId, (event) => {
          if (selectionTokenRef.current !== token) return;
          if (event.type === "progress") {
            setTimeline((prev) => [...prev, { kind: "step", title: event.step, detail: event.detail }]);
          } else if (event.type === "source_url") {
            setTimeline((prev) => {
              const last = prev[prev.length - 1];
              if (
                last &&
                last.kind === "sourceGroup" &&
                last.topic === event.topic &&
                last.toolName === event.tool_name
              ) {
                // Explicit annotation: without it, this object literal is inferred outside any
                // contextual type (it's a `const`, not written inline in the `return`), so
                // `kind` widens to `string` and fails to satisfy `TimelineEntry` below.
                const updated: TimelineEntry = {
                  ...last,
                  items: [...last.items, { title: event.title, url: event.url }],
                };
                return [...prev.slice(0, -1), updated];
              }
              return [
                ...prev,
                {
                  kind: "sourceGroup" as const,
                  topic: event.topic,
                  toolName: event.tool_name,
                  items: [{ title: event.title, url: event.url }],
                },
              ];
            });
          } else if (event.type === "source") {
            sourceCount += 1;
            setSources((prev) => [...prev, { topic: event.topic, summary: event.summary }]);
            setTimeline((prev) => [...prev, { kind: "sourceSummary", topic: event.topic, summary: event.summary }]);
          } else {
            setThreadId(event.thread_id);
            if (event.type === "done") setReport(event.report);
            terminal = event;
          }
        });
```

Replace the three `setSteps([]);` reset calls (in `startRun`, `resetAll`, and `selectSession`)
with `setTimeline([]);`.

Replace the `<ResearchDrawer .../>` prop:

```tsx
            <ResearchDrawer
              title={topic}
              mode={drawerMode}
              timeline={timeline}
              sources={sources}
              report={report}
              isRunning={phase === "running"}
              onClose={() => setDrawerOpen(false)}
            />
```

- [ ] **Step 5: Run frontend checks**

Run (from `frontend/`): `npm run lint` then `npm run build`
Expected: both succeed with no errors (the inline eslint-disable comment covers the one
`<img>` usage; everything else is plain TypeScript/JSX with no new type errors).

- [ ] **Step 6: Manual browser verification**

Start the backend (`uvicorn agentdrops.main:app --reload --port 8000` from `backend/`, plus
`docker compose up -d` and the Celery worker per `backend/CLAUDE.md`/README) and the frontend
(`npm run dev` from `frontend/`). In the browser:
1. Start a new research run. Confirm the drawer opens showing shimmering skeleton bars (not
   "Waiting to start...") until the first progress event arrives.
2. Once steps start streaming, confirm each step shows its full description text (not just the
   currently-active one), with a sparkle icon on completed steps and a spinner on the active one.
3. Confirm source chip groups appear inline between steps (grouped by tool, with favicon +
   title, clicking through to the URL), and a summary card appears once a topic's research
   finishes — not one aggregated block at the very end.

If no browser is available in this environment, run the lint/build checks only and say so
explicitly rather than claiming the UI was verified.

- [ ] **Step 7: Commit**

```bash
cd frontend
git add src/lib/types.ts src/components/ui/skeleton.tsx src/components/app/research-drawer.tsx src/app/page.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): merged progress timeline with skeleton loading and source chips

EOF
)"
```

---

### Task 4: Frontend — render the report as real markdown

**Files:**
- Modify: `frontend/package.json` (new dependency)
- Modify: `frontend/src/components/app/research-drawer.tsx`

**Interfaces:**
- Consumes: `report: string | null` (unchanged prop, already markdown-formatted text from the
  backend writer).
- Produces: no new exports; `ReportView`'s rendering behavior changes only.

- [ ] **Step 1: Add the dependency**

Run (from `frontend/`): `npm install react-markdown`

- [ ] **Step 2: Update `ReportView`**

Add the import at the top of `research-drawer.tsx`:

```tsx
import ReactMarkdown from "react-markdown";
```

Replace the `<div className="whitespace-pre-wrap ...">{report ?? "..."}</div>` block inside
`ReportView` with:

```tsx
      <div className="text-sm leading-relaxed text-muted-foreground">
        {report ? (
          <ReactMarkdown
            components={{
              h1: ({ children }) => (
                <h1 className="mb-2 mt-4 text-base font-semibold text-foreground first:mt-0">{children}</h1>
              ),
              h2: ({ children }) => (
                <h2 className="mb-2 mt-4 text-base font-semibold text-foreground first:mt-0">{children}</h2>
              ),
              h3: ({ children }) => (
                <h3 className="mb-1 mt-3 text-sm font-semibold text-foreground">{children}</h3>
              ),
              p: ({ children }) => <p className="mb-3 leading-relaxed">{children}</p>,
              a: ({ href, children }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="text-blue-500 underline underline-offset-2"
                >
                  {children}
                </a>
              ),
              ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5">{children}</ul>,
              ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5">{children}</ol>,
              li: ({ children }) => <li>{children}</li>,
              strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
            }}
          >
            {report}
          </ReactMarkdown>
        ) : (
          "Report not available yet."
        )}
      </div>
```

- [ ] **Step 3: Run frontend checks**

Run (from `frontend/`): `npm run lint` then `npm run build`
Expected: both succeed.

- [ ] **Step 4: Manual browser verification**

Open a completed research session (either freshly finished, or reopened from the sidebar) and
switch to the paragraph report. Confirm headings render as actual headings (not literal `##`
text) and inline citation links render as clickable blue links (not literal `[text](url)`).

If no browser is available, run the lint/build checks only and say so explicitly.

- [ ] **Step 5: Commit**

```bash
cd frontend
git add package.json package-lock.json src/components/app/research-drawer.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): render the report body as real markdown

EOF
)"
```

---

### Task 5: Frontend — header export menu replaces bottom Copy/Export buttons

**Note:** this task was revised after plan approval. Concurrent work already in the working tree
(a teammate's sessions-pinning branch, uncommitted) removed the header's old "Show thinking"
button and replaced the plain placeholder Copy/Export buttons with a real `CopyButton`
(clipboard copy) plus a disabled "Coming soon" Export button. The steps below relocate that
*existing, functional* pair into a header dropdown rather than relabeling inert placeholders —
nothing about the copy/export behavior itself changes, only where it renders.

**Files:**
- Modify: `frontend/src/components/app/research-drawer.tsx`

**Interfaces:**
- Consumes: `mode: DrawerMode`, `title: string`, `report: string | null`, `sources:
  ResearchSource[]` (all already in scope inside `ResearchDrawer`), and the existing
  `CopyButton({ label, text }: { label: string; text: string })` component already defined
  above `ResearchDrawer` in this file.
- Produces: no new exports.

- [ ] **Step 1: Re-add `ChevronDown` to the icon import**

`research-drawer.tsx` currently imports `{ CheckCircle2, Circle, Loader2, X }` from
`lucide-react` — `ChevronDown` was dropped when the old "Show thinking" button was removed, but
the new dropdown needs it back. Update the import to:

```tsx
import { CheckCircle2, ChevronDown, Circle, Loader2, X } from "lucide-react";
```

- [ ] **Step 2: Add the `ExportMenu` component**

Add this function above `ResearchDrawer` in `research-drawer.tsx` (below the existing
`CopyButton` definition):

```tsx
function ExportMenu({
  mode,
  report,
  sources,
}: {
  mode: DrawerMode;
  report: string | null;
  sources: ResearchSource[];
}) {
  const [open, setOpen] = useState(false);
  if (mode === "progress") return null;

  const copyProps =
    mode === "report"
      ? { label: "Copy report", text: report ?? "" }
      : {
          label: "Copy table",
          text: ["Topic\tFinding", ...sources.map((s) => `${s.topic}\t${s.summary}`)].join("\n"),
        };
  const exportLabel = mode === "report" ? "Export as PDF" : "Export as Excel";

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        Share and export
        <ChevronDown className="h-3.5 w-3.5" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-10 mt-1 flex w-44 flex-col gap-1 rounded-md border bg-card p-1.5 shadow-md">
          <CopyButton {...copyProps} />
          <button
            disabled
            title="Coming soon"
            className="cursor-not-allowed rounded-md border px-3 py-1.5 text-sm text-muted-foreground/60"
          >
            {exportLabel}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Wire it into the header, remove the bottom button rows**

Replace `ResearchDrawer`'s current header:

```tsx
        <button
          onClick={onClose}
          className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
```

with:

```tsx
        <div className="flex shrink-0 items-center gap-3">
          <ExportMenu mode={mode} report={report} sources={sources} />
          <button
            onClick={onClose}
            className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
```

(The status icon + title block above it, and the outer `flex items-center justify-between
border-b px-5 py-3` container, are unchanged.)

Remove the bottom `<div className="flex gap-2 border-t pt-4">...</div>` block from both
`ReportView` (containing `<CopyButton label="Copy report" .../>` and the disabled "Export as
PDF" button) and `TableViewMode` (containing `<CopyButton label="Copy table" .../>` and the
disabled "Export as Excel" button) — that functionality now lives in the header `ExportMenu`.
Leave the rest of both functions (heading, source count, body) unchanged.

- [ ] **Step 4: Run frontend checks**

Run (from `frontend/`): `npm run lint` then `npm run build`
Expected: both succeed.

- [ ] **Step 5: Manual browser verification**

Open a completed session's report or table view. Confirm "Share and export" appears in the
header next to the close button, toggles a dropdown containing a working "Copy report"/"Copy
table" button (verify it actually copies — check the clipboard or the "Copied!" label flip) and
a disabled "Export..." button, and that the bottom of the panel no longer has a duplicate button
row.

If no browser is available, run the lint/build checks only and say so explicitly.

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/components/app/research-drawer.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): move report/table export actions into a header menu

EOF
)"
```

---

### Task 6: Frontend — chat topic-card shows a timestamp

**Files:**
- Modify: `frontend/src/lib/utils.ts`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/components/app/chat-panel.tsx`

**Interfaces:**
- Produces: `formatTimestamp(iso: string): string` in `lib/utils.ts`, e.g.
  `formatTimestamp("2026-07-29T22:53:00Z")` → `"29 Jul, 22:53"` (exact minute/format depends on
  the browser's `Intl` locale data, not asserted byte-for-byte in this plan since there's no
  frontend test suite — verified visually in Step 5).
- `ChatPanel` gains a `topicStartedAt: string | null` prop.

- [ ] **Step 1: Add the formatter**

Add to `frontend/src/lib/utils.ts`:

```ts
export function formatTimestamp(iso: string): string {
  return new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}
```

- [ ] **Step 2: Track `topicStartedAt` in `page.tsx`**

Add the state declaration alongside the other topic-related state:

```tsx
  const [topicStartedAt, setTopicStartedAt] = useState<string | null>(null);
```

In `startRun()`, add `setTopicStartedAt(new Date().toISOString());` alongside the other reset
calls.

In `resetAll()`, add `setTopicStartedAt(null);` alongside the other reset calls.

In `selectSession()`, add `setTopicStartedAt(session.created_at);` right after `setTopic(session.title);`.

Pass the new prop into `ChatPanel`:

```tsx
        <ChatPanel
          phase={phase}
          setPhase={setPhase}
          topic={topic}
          setTopic={setTopic}
          topicStartedAt={topicStartedAt}
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
        />
```

- [ ] **Step 3: Update `ChatPanel`**

Update the imports at the top of `chat-panel.tsx`:

```tsx
import { ArrowUp, Search, Sparkles } from "lucide-react";
import { CLARIFY_CHIPS, SUGGESTIONS } from "@/lib/mock-data";
import { Message, Phase, StreamEvent } from "@/lib/types";
import { cn, formatTimestamp } from "@/lib/utils";
```

(`CheckCircle2`/`Loader2` are removed — they had no other use in this file besides the topic
card. `Sparkles` stays: it's already used for the hero empty-state icon elsewhere in this file,
from concurrent work already in the tree.)

Add `topicStartedAt: string | null;` to the destructured props and their type block (right after
`topic`/`setTopic`).

Replace the topic-card block:

```tsx
            {(phase === "running" || phase === "complete" || phase === "delivered") &&
              topic && (
                <button
                  onClick={onOpenDrawer}
                  className="flex items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors hover:bg-accent"
                >
                  <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{topic}</div>
                    <div className="text-xs text-muted-foreground">
                      {topicStartedAt ? formatTimestamp(topicStartedAt) : "Researching..."}
                    </div>
                  </div>
                </button>
              )}
```

- [ ] **Step 4: Run frontend checks**

Run (from `frontend/`): `npm run lint` then `npm run build`
Expected: both succeed.

- [ ] **Step 5: Manual browser verification**

Start a research run and reopen a past session from the sidebar. Confirm the topic card in the
chat pane shows a search icon and a formatted date/time (e.g. "29 Jul, 22:53") instead of
"Researching..."/"Research complete" text in both cases.

If no browser is available, run the lint/build checks only and say so explicitly.

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/lib/utils.ts src/app/page.tsx src/components/app/chat-panel.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): show a timestamp on the chat topic-card instead of status text

EOF
)"
```
