# Context Hub design

Date: 2026-08-23

## Problem

Research today runs entirely against the live web (Tavily). There's no way to bring in
enterprise/internal knowledge — internal reports, wikis, PDFs — as context for a research run.
Context Hub adds an optional, global knowledge base: users upload files or URLs once, and any
future research turn can opt in to querying that knowledge base alongside web search.

## Goals

- Upload files (PDF/DOCX/TXT/CSV) or point at a URL; extract and store their content so it's
  queryable by the research agent.
- Global knowledge base: content persists independently of any single research thread and is
  available to every future session.
- Per-turn opt-in: a toggle decides whether a given research turn's agent may consult Context Hub
  at all. Off by default — a user with nothing uploaded should see no behavior change.
- Relevant-snippet retrieval: a 300-page document must not be dumped wholesale into the agent's
  context. The agent queries Context Hub like a search tool and gets back the most relevant
  chunks for its current research topic.

## Non-goals

- Per-session/per-thread scoped knowledge (explicitly rejected in favor of one global hub).
- Real-time collaborative editing of uploaded content.
- Any document types beyond PDF/DOCX/TXT/CSV/URL in this pass.

## Data model

New Alembic migration enables the `vector` extension (pgvector) and adds two tables, following
the existing pattern in `db/models/sessions.py` / `db/migrations/versions/`.

**`contexthub_documents`**

| column | type | notes |
|---|---|---|
| `id` | uuid, pk | |
| `title` | text | filename or URL, used in list UI and in snippets |
| `source_type` | text | `file` \| `url` |
| `source_name` | text | original filename or URL |
| `content_type` | text | `pdf` \| `docx` \| `txt` \| `csv` \| `url` |
| `status` | text | `processing` \| `ready` \| `failed` |
| `error` | text, nullable | set on `failed` |
| `minio_key` | text, nullable | raw file location; null for `url` sources (no bytes to keep) |
| `created_at` / `updated_at` | timestamptz | |

**`contexthub_chunks`**

| column | type | notes |
|---|---|---|
| `id` | uuid, pk | |
| `document_id` | uuid, fk -> `contexthub_documents.id`, `ON DELETE CASCADE` | |
| `chunk_index` | int | order within the document |
| `content` | text | chunk text |
| `embedding` | `vector(1536)` | matches `text-embedding-3-small`; IVFFlat/HNSW index for cosine search |

No `thread_id` on either table — the hub is global, per the approved design.

## Storage

Raw uploaded files go into a new `contexthub` bucket in the existing minio instance (already in
`docker-compose.yml` and `Settings`, currently unused by any code). URL sources store only
extracted text; there's no original file to keep.

## Settings additions (`config/settings.py`)

```
minio_contexthub_bucket: str = "contexthub"
embedding_api_key: str
embedding_base_url: str = "https://api.openai.com/v1"
embedding_model: str = "text-embedding-3-small"
contexthub_chunk_size: int = 1000
contexthub_chunk_overlap: int = 150
contexthub_search_top_k: int = 5
```

New dependencies: `pypdf`, `python-docx`, `pgvector` (SQLAlchemy `Vector` type). The `openai`
package is already a dependency (via `langchain-openai`) and is reused directly for embeddings —
this is a deliberate exception to "never import provider SDKs" from `agents/llm.py`, since
embeddings aren't a chat-model call routed through `init_chat_model`.

## Ingestion pipeline

New package `agents/contexthub/`:

- `extract.py` — text extraction per source type: `pypdf` (PDF), `python-docx` (DOCX), plain read
  (TXT/CSV), httpx fetch + basic HTML-to-text strip (URL).
- `chunk.py` — sliding-window chunking using `contexthub_chunk_size`/`contexthub_chunk_overlap`.
- `embeddings.py` — thin OpenAI-compatible embeddings client, used both at ingest (embed each
  chunk) and at query time (embed the search query).
- `methods.py` — `run_contexthub_search_pipeline(query, top_k)`: embeds the query, runs a pgvector
  cosine-similarity query (`ORDER BY embedding <=> :query_vector LIMIT top_k`) against
  `contexthub_chunks`, formats results with document title + snippet — mirrors the
  search→format shape of `agents/research/methods.py::run_search_pipeline`.
- `tools.py` — `make_context_hub_tool(...)` adapts `run_contexthub_search_pipeline` into a
  `context_hub_search` LangChain tool, the same shape as `agents/tools.py::make_tavily_tool`.

**Flow:**

1. `POST /v1/contexthub/documents` (multipart file) or `POST /v1/contexthub/urls` (`{url}` body)
   hits `ContextHubService`, which inserts a `contexthub_documents` row (`status=processing`),
   uploads raw bytes to minio (file sources only), and enqueues a new Celery task.
2. `agentdrops.ingest_contexthub_document` (new task in `worker/tasks.py`, same shape as
   `run_turn_task._execute`: owns its own engine/session factory, catches setup failures) —
   extracts text, chunks it, embeds each chunk, bulk-inserts `contexthub_chunks`, and flips
   `status` to `ready` (or `failed` + `error` message on exception).
3. The sidebar Context Hub panel re-fetches `GET /v1/contexthub/documents` to reflect status —
   no SSE/pub-sub wiring needed since this isn't tied to a research thread.

## Agent integration & the per-turn toggle

The graph is already rebuilt fresh on every turn (`worker/tasks.py::_execute` calls
`build_market_researcher(...)` per Celery task invocation, not once at startup) — so whether
`context_hub_search` is in the tool list can be decided at build time per turn, with no need to
thread a flag through LangGraph state.

- `ChatRequest` (`api/v1/schema.py`) gains `use_context_hub: bool = False`.
- `api/v1/chat.py` → `ChatQueueService.enqueue` → `run_turn_task.delay(thread_id, message,
  operation, use_context_hub)` → `worker/tasks.py::_execute` → `build_market_researcher(settings,
  client, saver, use_context_hub=use_context_hub)`.
- `build_market_researcher` conditionally appends `context_hub_search` (built via
  `make_context_hub_tool`) to the `tools` list passed into `build_research_graph`, alongside
  `tavily_search` and `think_tool`.
- Default `False`: a user with nothing uploaded (or who leaves the toggle off) sees no behavior
  change from today.

## API surface

New `api/v1/contexthub.py` + `service/contexthub_service.py`, following the existing
router-is-thin/service-owns-logic split:

- `POST /v1/contexthub/documents` — multipart file upload.
- `POST /v1/contexthub/urls` — `{url: str}` body.
- `GET /v1/contexthub/documents` — list all documents with status, for the sidebar panel.
- `DELETE /v1/contexthub/documents/{id}` — deletes the DB row (cascades to chunks) and the minio
  object if one exists.

## Frontend

- A new "Context Hub" icon/button in `sidebar.tsx`, opening a panel: lists documents with status
  (processing/ready/failed), a file-drop + URL-input uploader, delete per item.
- New functions in `src/lib/api.ts` (`listContextHubDocuments`, `uploadContextHubFile`,
  `addContextHubUrl`, `deleteContextHubDocument`) and matching types in `src/lib/types.ts`.
- A toggle ("Use uploaded knowledge") in `ChatPanel`'s message-send area, controlling
  `use_context_hub` on `/v1/chat` and `/v1/chat/stream` requests. State lives in `page.tsx`
  (matching the existing single-client-component pattern) and is passed down as a prop.
- No polling: the document list is manually re-fetched after upload/delete; it isn't part of the
  SSE stream since it isn't tied to any research thread.

## Testing

- Backend: unit tests for `chunk.py` (boundary/overlap correctness), `extract.py` (per format,
  using small fixture files), `methods.py` (mocked embeddings client + a test-database
  pgvector query). Service-layer tests for `ContextHubService` (upload → processing row → task
  enqueued; delete → row + minio object gone). Router tests for the new endpoints. Graph test
  confirming `use_context_hub=True` adds `context_hub_search` to the built tool list and `False`
  omits it, per the existing `FakeChatModel`-based graph tests.
- Frontend: component test for the upload panel (file + URL paths, delete), and a check that the
  toggle's value is included in outgoing chat requests.

## Out of scope / follow-ups

- Chunk re-ranking beyond plain cosine similarity.
- Per-document access control / multi-tenant knowledge bases.
- Automatic re-ingestion when a source URL's content changes.
