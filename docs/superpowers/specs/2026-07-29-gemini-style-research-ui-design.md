# Gemini-style research drawer: skeleton loading, live source narrative, rendered report

Date: 2026-07-29

## Context

The research drawer (`frontend/src/components/app/research-drawer.tsx`) and its chat-panel
trigger (`frontend/src/components/app/chat-panel.tsx`) currently show:

- A static "Waiting to start..." row before the first progress event arrives.
- A compact step checklist where only the *active* step's `detail` text is shown.
- A single aggregated "N SOURCES REVIEWED" card list at the bottom of the progress view,
  populated from one `source` event per delegated research topic (topic + truncated summary,
  no per-result URLs).
- A report view that renders the markdown-formatted report text with `whitespace-pre-wrap`,
  i.e. as literal text — `## Executive Summary` and `[IMARC Group](url)` show up unrendered.
- A chat topic-card with a status icon (spinner/checkmark) and "Researching..."/"Research
  complete" text.

This spec adopts several presentation patterns from Gemini's Deep Research UI (per screenshots
walked through in conversation) where they improve on the above, while keeping scope to what
this app's backend can actually support without a larger rework.

## Goals

1. Fill the visible gap between "drawer opens" and "first progress event arrives" with a
   skeleton-loading placeholder instead of static text.
2. Show the full narrative of a research run: every step's descriptive text (not just the
   active one), and the per-*URL* sources found along the way, interleaved in arrival order —
   not aggregated into one block at the end.
3. Render the final report as actual formatted markdown.
4. Minor chrome alignment: reposition the existing (already non-functional) Copy/Export buttons
   into the drawer header; show a timestamp on the chat topic-card instead of status text.

## Non-goals

- No new "Contents" (TOC) navigation, no "Share and export" backend functionality, no "Create"
  feature — these are Gemini product features that don't map to anything this app does today.
- No change to how `sources: ResearchSource[]` (topic + summary) feeds `ReportView` /
  `TableViewMode` — those keep working exactly as they do today.
- No change to the `/v1/chat/stream` terminal event contract (`clarify` / `done` / `error`) or
  to session persistence.

## Backend: `source_url` event

Today, `SearchResult` (`tool_name`, `title`, `url`, `snippet`) exists only transiently inside
`run_search_pipeline` (`backend/src/agentdrops/agents/research/methods.py`) — by the time the
supervisor sees anything, it's a single flattened `compressed_research` string per topic. To
show real per-URL chips, individual results need to be streamed out as they're found.

### Change 1 — emit one custom write per deduped result

In `run_search_pipeline`, right after `deduplicate_search_results` (before summarization, so
chips can appear before the LLM synthesis step finishes):

```python
from langgraph.config import get_stream_writer
...
deduped = deduplicate_search_results(results)
writer = get_stream_writer()
for result in deduped:
    writer({"type": "source_url", "tool_name": result.tool_name, "title": result.title, "url": result.url})
```

### Change 2 — `run_topic` relays the nested subgraph's custom writes

`run_topic` in `backend/src/agentdrops/agents/supervisor/graph.py` currently calls
`research_graph.ainvoke(...)`. Per this repo's own documented invariant (`agents/graph.py`'s
`supervisor` node docstring), a bare nested `ainvoke` is an isolated run whose custom writes
never reach the outer consumer. `run_topic` needs the same fix already applied one level up:

```python
async def run_topic(call: ToolCall) -> ToolMessage:
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
    writer({"type": "source", "topic": topic, "summary": final_state["compressed_research"][:280]})
    return ToolMessage(
        content=final_state["compressed_research"], tool_call_id=call["id"], name="ConductResearch"
    )
```

The relayed event shape on the wire is `{"type": "source_url", "tool_name": str, "title": str,
"url": str, "topic": str}` — `topic` is merged in by `run_topic`, not known by
`run_search_pipeline` itself.

This is additive: existing `progress` and `source` (per-topic summary) events are unchanged, so
`ReportView`, `TableViewMode`, and sourceCount all keep working as-is.

Concurrent topics (`max_concurrent_researchers > 1`) can already interleave `progress`/`source`
events today since `run_topic` invocations run under `asyncio.gather`; `source_url` inherits the
same characteristic. This isn't a new problem, and each event carries `topic` so the frontend
can still group correctly per topic even if two topics' events interleave on the wire.

### Test changes

- `tests/unit/agents/supervisor/test_graph.py`: `_FakeResearchGraph` only implements
  `.ainvoke()` today — add an `.astream()` yielding a `("custom", {...})` chunk then a
  `("values", {...})` chunk, since the real code no longer calls `.ainvoke()`. Add a new test
  asserting a `source_url` chunk from the fake subgraph is relayed with `topic` merged in.
- `tests/unit/agents/research/test_methods.py`: new test monkeypatching
  `agentdrops.agents.research.methods.get_stream_writer` to assert one `source_url` write per
  deduped result, in dedup order, before summarization is awaited.

### API docs

Update the SSE event list in `backend/src/agentdrops/api/v1/chat.py`'s `chat_stream` docstring
to document `source_url`, mirroring the existing `progress`/`source` doc lines (per the CLAUDE.md
rule that SSE event shapes are documented there and mirrored in `frontend/src/lib/types.ts`).

## Frontend: merged timeline in the progress view

### New state: `timeline`

`page.tsx` adds a `timeline` state — an ordered array appended to as SSE events arrive,
alongside (not replacing) the existing `steps`/`sources` state, which keep feeding `ReportView`/
`TableViewMode` exactly as today:

```ts
type TimelineEntry =
  | { kind: "step"; title: string; detail?: string }
  | { kind: "sourceGroup"; topic: string; toolName: string; items: { title: string; url: string }[] }
  | { kind: "sourceSummary"; topic: string; summary: string };
```

Event handling in `sendMessage`'s per-event callback (`page.tsx`):

- `progress` → append a `{kind:"step", ...}` entry.
- `source_url` → if the last timeline entry is a `sourceGroup` with the same `topic` and
  `tool_name`, append `{title, url}` into its `items` (new array reference, immutable update);
  otherwise start a new `sourceGroup` entry.
- `source` (existing per-topic summary, unchanged wire shape) → in addition to the existing
  `setSources` append, also push a `{kind:"sourceSummary", topic, summary}` timeline entry.

`TimelineEntry` is a UI-only grouping concept and lives alongside the other view types (not in
`lib/types.ts`, which stays limited to wire/API shapes). `StreamEvent` in `lib/types.ts` gains:

```ts
| { type: "source_url"; topic: string; tool_name: string; title: string; url: string }
```

No change needed to `api.ts`'s SSE parser — it already does a generic `JSON.parse(...) as
StreamEvent` per line.

### `ProgressView` rendering

- Replace the `steps.map(...)` checklist with a `timeline.map(...)` that switches on `kind`:
  - `step`: bullet uses a `Sparkles` icon (lucide) instead of CheckCircle2/Circle, for all
    entries; the currently-running last step (only when `isRunning`) shows the spinner instead.
    Renders the full `detail` text for every step, not just the active one.
  - `sourceGroup`: a small tool-name label followed by a responsive grid of chips — each chip
    shows a favicon (`https://www.google.com/s2/favicons?domain=<hostname>`, hostname parsed
    client-side from `item.url`) and the truncated `title`, linking to `item.url`.
  - `sourceSummary`: a small card with the topic and its compressed summary, replacing what's
    currently the bottom-of-drawer aggregated "N SOURCES REVIEWED" block (removed — it would now
    duplicate the inline `sourceGroup`/`sourceSummary` entries).
- Skeleton state: when `timeline.length === 0 && isRunning`, render shimmering placeholder
  groups (new `Skeleton` primitive, see below) instead of "Waiting to start...". When
  `timeline.length === 0 && !isRunning` (the `clarifying`/`queued` states), keep today's
  "Waiting to start..." text — nothing is actually running yet.
- New `frontend/src/components/ui/skeleton.tsx`, following the same convention as the existing
  `ui/table.tsx`: `<div className={cn("bg-accent animate-pulse rounded-md", className)} />`.

### Report rendering

- Add `react-markdown` as a dependency. `ReportView` renders `report` through
  `<ReactMarkdown components={...}>` instead of a `whitespace-pre-wrap` div, with hand-styled
  `components` overrides (no `@tailwindcss/typography` — this repo doesn't have it, and the
  report only needs headings/paragraphs/links/lists/bold, not full prose CSS):
  - `h1`/`h2`/`h3` → semibold headings sized down from the drawer's existing `text-lg` title.
  - `p` → the existing `text-sm leading-relaxed text-muted-foreground` styling.
  - `a` → `text-blue-500 underline underline-offset-2`, `target="_blank" rel="noreferrer"`.
  - `ul`/`li` → standard list styling consistent with the rest of the drawer.
- `TableViewMode` is untouched — it renders structured `sources`, not the markdown report body.

### Header chrome

- The drawer header (`research-drawer.tsx`) gets a lightweight, hand-rolled dropdown (no new UI
  library — this repo has no Radix/shadcn menu primitive yet, and one popover doesn't justify
  adding one) labeled "Share and export", visible only in `report`/`table` mode, containing the
  existing "Copy report"/"Export as PDF" (or "Copy table"/"Export as Excel") actions — same
  placeholder behavior as today, just moved from the bottom of the panel into the header next to
  "Show thinking". The bottom button row is removed so the actions aren't duplicated.
- No "Contents" (TOC) nav, no "Create" button — out of scope (see Non-goals).

### Chat topic-card

- `chat-panel.tsx`'s topic card subtitle switches from "Researching..."/"Research complete" to
  a formatted timestamp (e.g. "29 Jul, 22:53"), and the icon switches from
  Loader2/CheckCircle2 to a static search-style icon (lucide `Search` or `Globe`).
- `page.tsx` needs to track when a run started: a new `topicStartedAt: string | null` state, set
  to `new Date().toISOString()` in `startRun()`, and to `session.created_at` when reopening a
  session via `selectSession()`. A small formatter (in `lib/utils.ts`) renders it as `"29 Jul,
  22:53"` via `Intl.DateTimeFormat`.
- Since this removes the only visible "is it still running" indicator from the chat pane, the
  drawer's own progress view (spinner on the active step) remains the source of truth for live
  status — acceptable since the drawer auto-opens on `startRun()`.

## Testing

- Backend: unit tests as described above (`test_graph.py`, `test_methods.py`), run via `pytest`
  from `backend/`.
- Frontend: this repo has no frontend test suite; verification is `npm run lint` + `npm run
  build`, plus manually running a research turn end-to-end (`make run` + `make worker`
  equivalent — `uvicorn` + Celery worker + `npm run dev`) to confirm: skeleton shows briefly,
  steps show full detail text, source chips appear grouped and linked, the report renders
  formatted markdown, and the topic-card shows a timestamp.

## Open risks

- Favicon requests go to `google.com/s2/favicons`, a third-party call from the client per chip —
  acceptable for an internal tool, but worth knowing this is not self-hosted.
- `react-markdown` is a new frontend dependency; no others were rejected in favor of it here.
