# Context Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users upload files (PDF/DOCX/TXT/CSV) or URLs into a global, embeddings-backed knowledge base, and give research turns an optional (`use_context_hub`, default off) tool to query it for relevant snippets alongside live web search.

**Architecture:** Uploaded content is extracted, chunked, and embedded (OpenAI-compatible embeddings endpoint) into a new `contexthub_chunks` pgvector table via an async Celery ingestion task, mirroring the existing `run_turn_task` shape. A new `context_hub_search` LangChain tool (same shape as `tavily_search`) does cosine-similarity retrieval against those chunks. Because `build_market_researcher(...)` is already rebuilt fresh on every chat turn (`worker/tasks.py::_execute`), the tool is included or omitted per turn based on a `use_context_hub` flag threaded through `ChatRequest` — no LangGraph state plumbing needed. Raw files live in a new minio bucket; URL sources store only extracted text.

**Tech Stack:** FastAPI, SQLAlchemy (async) + pgvector, Celery, minio (raw storage), pypdf/python-docx (extraction), httpx (embeddings + URL fetch), Next.js/React (frontend).

**Spec:** `docs/superpowers/specs/2026-08-23-contexthub-design.md`

## Global Constraints

- Embedding model: OpenAI-compatible endpoint, default `text-embedding-3-small` (1536 dims) — settings `embedding_api_key` (required), `embedding_base_url` (default `https://api.openai.com/v1`), `embedding_model` (default `text-embedding-3-small`).
- Chunking: `contexthub_chunk_size` default `1000`, `contexthub_chunk_overlap` default `150` (chars).
- Retrieval: `contexthub_search_top_k` default `5`.
- Context Hub is global — no `thread_id` scoping anywhere in its schema.
- `use_context_hub` defaults to `False` everywhere it's threaded — no behavior change for users who upload nothing.
- Content types accepted: `pdf`, `docx`, `txt`, `csv` (files) and `url`. Nothing else.
- Follow existing patterns exactly: routers stay thin (extract request → call service → map response), services own business logic, repositories own SQL, `Settings` is the single source of config, tests mock at the same boundary existing tests do (fakes for service/router tests, real-Postgres-with-autoskip for repository tests).

---

## Task 1: Settings, dependencies, and pgvector-enabled Postgres

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/.env.example`
- Modify: `backend/docker-compose.yml`
- Modify: `backend/src/agentdrops/config/settings.py`
- Modify: `backend/tests/unit/test_config.py`
- Modify: `backend/tests/unit/agents/conftest.py`

**Interfaces:**
- Produces: `Settings.minio_contexthub_bucket: str`, `Settings.embedding_api_key: str`, `Settings.embedding_base_url: str`, `Settings.embedding_model: str`, `Settings.contexthub_chunk_size: int`, `Settings.contexthub_chunk_overlap: int`, `Settings.contexthub_search_top_k: int`, `Settings.contexthub_max_upload_mb: int` — every later task reads these off `Settings`.

- [ ] **Step 1: Write the failing test — new required setting**

Add to `backend/tests/unit/test_config.py`, in both `test_settings_loads_required_fields_from_env` and `_base_env`/`test_settings_missing_required_field_raises`:

```python
monkeypatch.setenv("EMBEDDING_API_KEY", "embed-test")
```

(add this line next to the other `monkeypatch.setenv(...)` calls in `test_settings_loads_required_fields_from_env` and in `_base_env`; add `"EMBEDDING_API_KEY"` to the list of keys deleted in `test_settings_missing_required_field_raises`)

Also add a new assertion at the end of `test_settings_loads_required_fields_from_env`:

```python
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.contexthub_chunk_size == 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_config.py -v`
Expected: FAIL — `embedding_api_key` not yet a field on `Settings` (or `ValidationError` for an unknown/missing field, depending which assertion trips first).

- [ ] **Step 3: Add the new settings fields**

In `backend/src/agentdrops/config/settings.py`, add after the existing `minio_secret_key: str` line:

```python
    minio_contexthub_bucket: str = "contexthub"
    """Bucket for raw Context Hub file uploads (extracted text for URL sources isn't stored here)."""

    embedding_api_key: str
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    """Must produce 1536-dim vectors to match `contexthub_chunks.embedding`'s column type."""

    contexthub_chunk_size: int = 1000
    contexthub_chunk_overlap: int = 150
    contexthub_search_top_k: int = 5
    contexthub_max_upload_mb: int = 50
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Update `make_settings` test helper**

In `backend/tests/unit/agents/conftest.py`, add to the `defaults` dict in `make_settings`:

```python
        "embedding_api_key": "embed-test",
```

- [ ] **Step 6: Add new dependencies**

In `backend/pyproject.toml`, add to `dependencies`:

```toml
    "pypdf>=4.2",
    "python-docx>=1.1",
    "pgvector>=0.3",
    "minio>=7.2",
    "python-multipart>=0.0.9",
```

(`python-multipart` is required by FastAPI for `UploadFile`/multipart form parsing — the upload endpoint in Task 10 needs it.)

Run: `cd backend && pip install -e ".[dev]"`
Expected: install succeeds, new packages present.

- [ ] **Step 7: Switch Postgres to a pgvector-enabled image**

In `backend/docker-compose.yml`, change:

```yaml
  postgres:
    image: postgres:16-alpine
```

to:

```yaml
  postgres:
    image: pgvector/pgvector:pg16
```

(Same Postgres 16, with the `vector` extension available for `CREATE EXTENSION vector` in Task 2. Everything else about the service — env, ports, volumes, healthcheck — is unchanged.)

Run: `cd backend && docker compose up -d postgres` then `docker compose exec postgres psql -U agentdrops -c "CREATE EXTENSION IF NOT EXISTS vector;"`
Expected: `CREATE EXTENSION` (or a no-op if you'd already run it) — proves the image ships the extension. If you have an existing `postgres_data` volume from the old image, recreate it first (`docker compose down -v` — only if this is a disposable dev volume, never on data you care about).

- [ ] **Step 8: Update `.env.example`**

In `backend/.env.example`, add after the `MINIO_SECRET_KEY=minioadmin` line:

```bash
# Context Hub — file/URL knowledge base the research agent can optionally query
# (per-turn opt-in; see agents/contexthub/). Embeddings call an OpenAI-wire-compatible
# endpoint independently of LLM_PROVIDER — point it at OpenAI, or any gateway you already
# use, that offers an /embeddings route.
MINIO_CONTEXTHUB_BUCKET=contexthub
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
```

- [ ] **Step 9: Commit**

```bash
git add backend/pyproject.toml backend/.env.example backend/docker-compose.yml \
  backend/src/agentdrops/config/settings.py backend/tests/unit/test_config.py \
  backend/tests/unit/agents/conftest.py
git commit -m "feat(contexthub): add settings, deps, and pgvector-enabled postgres"
```

---

## Task 2: Data model — migration and ORM models

**Files:**
- Create: `backend/src/agentdrops/db/models/contexthub.py`
- Modify: `backend/src/agentdrops/db/models/__init__.py`
- Create: `backend/src/agentdrops/db/migrations/versions/0006_add_contexthub_tables.py`

**Interfaces:**
- Consumes: `Settings.embedding_model` implies 1536-dim vectors (Task 1) — the migration hardcodes `1536` since column dimensionality can't read `Settings` at migration time; a future embedding-model change with a different dimension needs its own migration.
- Produces: `ContextHubDocumentTable`, `ContextHubChunkTable` ORM classes (`db/models/contexthub.py`) — Task 6's repository is the only consumer.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/db/test_contexthub_models.py`:

```python
from agentdrops.db.models import Base, ContextHubChunkTable, ContextHubDocumentTable


def test_contexthub_tables_registered_on_base_metadata() -> None:
    assert "contexthub_documents" in Base.metadata.tables
    assert "contexthub_chunks" in Base.metadata.tables


def test_contexthub_chunk_has_expected_columns() -> None:
    columns = {c.name for c in ContextHubChunkTable.__table__.columns}
    assert columns == {"id", "document_id", "chunk_index", "content", "embedding"}


def test_contexthub_document_has_expected_columns() -> None:
    columns = {c.name for c in ContextHubDocumentTable.__table__.columns}
    assert columns == {
        "id", "title", "source_type", "source_name", "content_type",
        "status", "error", "minio_key", "created_at", "updated_at",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/db/test_contexthub_models.py -v`
Expected: FAIL — `ContextHubChunkTable`/`ContextHubDocumentTable` don't exist yet.

- [ ] **Step 3: Add the ORM models**

Create `backend/src/agentdrops/db/models/contexthub.py`:

```python
"""ORM mapping for `contexthub_documents`/`contexthub_chunks`
(`db/migrations/versions/0006_add_contexthub_tables.py`)."""

from datetime import datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

EMBEDDING_DIM = 1536
"""Matches `text-embedding-3-small`; a different embedding model needs its own migration."""


class ContextHubDocumentTable(Base):
    __tablename__ = "contexthub_documents"

    id: Mapped[str] = mapped_column(sa.Text(), primary_key=True)
    title: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    content_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.Text(), nullable=False, server_default=sa.text("'processing'")
    )
    error: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    minio_key: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        onupdate=sa.text("now()"),
        nullable=False,
    )


class ContextHubChunkTable(Base):
    __tablename__ = "contexthub_chunks"

    id: Mapped[str] = mapped_column(sa.Text(), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        sa.Text(),
        sa.ForeignKey("contexthub_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
```

Replace the full contents of `backend/src/agentdrops/db/models/__init__.py` with:

```python
"""ORM models: the runtime schema for `agentdrops.repository` and the autogenerate
source-of-truth for Alembic. Importing this package registers every table on `Base.metadata`."""

from .audit_log import AuditLogTable
from .base import Base
from .contexthub import ContextHubChunkTable, ContextHubDocumentTable
from .sessions import SessionTable

__all__ = [
    "AuditLogTable",
    "Base",
    "ContextHubChunkTable",
    "ContextHubDocumentTable",
    "SessionTable",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/db/test_contexthub_models.py -v`
Expected: PASS

- [ ] **Step 5: Write the migration**

Create `backend/src/agentdrops/db/migrations/versions/0006_add_contexthub_tables.py`:

```python
# backend/src/agentdrops/db/migrations/versions/0006_add_contexthub_tables.py
"""add contexthub_documents and contexthub_chunks

Global knowledge-base tables backing agents/contexthub/ — the `context_hub_search` tool's
retrieval store. Requires the pgvector extension (image already switched to
pgvector/pgvector:pg16 in docker-compose.yml).

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "contexthub_documents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'processing'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("minio_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_contexthub_documents_created_at", "contexthub_documents", ["created_at"]
    )

    op.create_table(
        "contexthub_chunks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "document_id", sa.Text(),
            sa.ForeignKey(
                "contexthub_documents.id", ondelete="CASCADE",
                name="fk_contexthub_chunks_document_id_contexthub_documents",
            ),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    )
    op.create_index("ix_contexthub_chunks_document_id", "contexthub_chunks", ["document_id"])
    op.execute(
        "CREATE INDEX ix_contexthub_chunks_embedding ON contexthub_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_index("ix_contexthub_chunks_embedding", table_name="contexthub_chunks")
    op.drop_index("ix_contexthub_chunks_document_id", table_name="contexthub_chunks")
    op.drop_table("contexthub_chunks")
    op.drop_index("ix_contexthub_documents_created_at", table_name="contexthub_documents")
    op.drop_table("contexthub_documents")
```

- [ ] **Step 6: Apply the migration against the local Postgres**

Run: `cd backend && alembic upgrade head`
Expected: applies cleanly; `docker compose exec postgres psql -U agentdrops -c "\d contexthub_chunks"` shows the `embedding` column as `vector(1536)`.

- [ ] **Step 7: Commit**

```bash
git add backend/src/agentdrops/db/models/contexthub.py backend/src/agentdrops/db/models/__init__.py \
  backend/src/agentdrops/db/migrations/versions/0006_add_contexthub_tables.py \
  backend/tests/unit/db/test_contexthub_models.py
git commit -m "feat(contexthub): add contexthub_documents/contexthub_chunks tables"
```

---

## Task 3: Object storage — minio wrapper for raw files

**Files:**
- Create: `backend/src/agentdrops/storage/__init__.py`
- Create: `backend/src/agentdrops/storage/contexthub.py`
- Test: `backend/tests/unit/storage/__init__.py`
- Test: `backend/tests/unit/storage/conftest.py`
- Test: `backend/tests/unit/storage/test_contexthub_storage.py`

**Interfaces:**
- Consumes: `Settings.minio_endpoint`, `Settings.minio_access_key`, `Settings.minio_secret_key`, `Settings.minio_contexthub_bucket` (Task 1).
- Produces: `ContextHubStorage(settings: Settings)` with `async def put(self, key: str, data: bytes, content_type: str) -> None`, `async def get(self, key: str) -> bytes`, `async def delete(self, key: str) -> None` — Task 9's ingestion task and Task 9's `ContextHubService` both depend on this exact signature.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/storage/conftest.py`:

```python
"""Real-minio integration fixture (the docker-compose instance), auto-skipped when unreachable —
same shape as tests/unit/repository/conftest.py's Postgres auto-skip."""

import uuid

import pytest
from minio.error import S3Error
from urllib3.exceptions import MaxRetryError

from agentdrops.storage.contexthub import ContextHubStorage
from tests.unit.agents.conftest import make_settings


@pytest.fixture
def contexthub_storage() -> ContextHubStorage:
    settings = make_settings(minio_contexthub_bucket=f"contexthub-test-{uuid.uuid4().hex[:8]}")
    storage = ContextHubStorage(settings)
    try:
        storage.client.bucket_exists(settings.minio_contexthub_bucket)
    except (MaxRetryError, S3Error) as exc:
        pytest.skip(f"minio not reachable at {settings.minio_endpoint}: {exc}")
    return storage
```

Create `backend/tests/unit/storage/__init__.py` (empty).

Create `backend/tests/unit/storage/test_contexthub_storage.py`:

```python
import pytest

from agentdrops.storage.contexthub import ContextHubStorage


async def test_put_then_get_roundtrips_bytes(contexthub_storage: ContextHubStorage) -> None:
    await contexthub_storage.put("docs/one.txt", b"hello world", "text/plain")

    result = await contexthub_storage.get("docs/one.txt")

    assert result == b"hello world"


async def test_delete_removes_the_object(contexthub_storage: ContextHubStorage) -> None:
    await contexthub_storage.put("docs/two.txt", b"gone soon", "text/plain")

    await contexthub_storage.delete("docs/two.txt")

    with pytest.raises(Exception):
        await contexthub_storage.get("docs/two.txt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/storage/ -v`
Expected: FAIL — `agentdrops.storage` module doesn't exist yet.

- [ ] **Step 3: Implement the storage wrapper**

Create `backend/src/agentdrops/storage/__init__.py` (empty).

Create `backend/src/agentdrops/storage/contexthub.py`:

```python
"""Minio-backed raw-file storage for Context Hub uploads. Minio's client is synchronous, so
every call is wrapped in `asyncio.to_thread` to stay consistent with the rest of this async
codebase — this is the one place a blocking client is used."""

import asyncio
import io

from minio import Minio

from agentdrops.config import Settings


class ContextHubStorage:
    def __init__(self, settings: Settings) -> None:
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False,
        )
        self._bucket = settings.minio_contexthub_bucket

    async def _ensure_bucket(self) -> None:
        exists = await asyncio.to_thread(self.client.bucket_exists, self._bucket)
        if not exists:
            await asyncio.to_thread(self.client.make_bucket, self._bucket)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self._ensure_bucket()
        await asyncio.to_thread(
            self.client.put_object,
            self._bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type,
        )

    async def get(self, key: str) -> bytes:
        response = await asyncio.to_thread(self.client.get_object, self._bucket, key)
        try:
            return await asyncio.to_thread(response.read)
        finally:
            response.close()
            response.release_conn()

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.remove_object, self._bucket, key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && docker compose up -d minio && pytest tests/unit/storage/ -v`
Expected: PASS (or SKIPPED if minio isn't running locally — start it first with the compose command above).

- [ ] **Step 5: Commit**

```bash
git add backend/src/agentdrops/storage backend/tests/unit/storage
git commit -m "feat(contexthub): add minio-backed raw file storage"
```

---

## Task 4: Content extraction and chunking

**Files:**
- Create: `backend/src/agentdrops/agents/contexthub/__init__.py`
- Create: `backend/src/agentdrops/agents/contexthub/extract.py`
- Create: `backend/src/agentdrops/agents/contexthub/chunk.py`
- Test: `backend/tests/unit/agents/contexthub/__init__.py`
- Test: `backend/tests/unit/agents/contexthub/test_extract.py`
- Test: `backend/tests/unit/agents/contexthub/test_chunk.py`

**Interfaces:**
- Produces: `extract_file_text(content_type: str, data: bytes) -> str`, `async def fetch_url_text(url: str, client: httpx.AsyncClient) -> str`, `chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]` — Task 9's ingestion task calls all three.

- [ ] **Step 1: Write the failing tests — chunking**

Create `backend/tests/unit/agents/contexthub/__init__.py` (empty).

Create `backend/tests/unit/agents/contexthub/test_chunk.py`:

```python
from agentdrops.agents.contexthub.chunk import chunk_text


def test_short_text_returns_a_single_chunk() -> None:
    chunks = chunk_text("hello world", chunk_size=1000, overlap=150)

    assert chunks == ["hello world"]


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("", chunk_size=1000, overlap=150) == []


def test_long_text_is_split_with_overlap() -> None:
    text = "x" * 2500

    chunks = chunk_text(text, chunk_size=1000, overlap=150)

    assert len(chunks) == 3
    assert all(len(c) <= 1000 for c in chunks)
    # the overlap region (last 150 chars of chunk N) reappears at the start of chunk N+1
    assert chunks[0][-150:] == chunks[1][:150]
    assert chunks[1][-150:] == chunks[2][:150]


def test_whitespace_is_normalized_before_chunking() -> None:
    chunks = chunk_text("hello\n\n   world  \t foo", chunk_size=1000, overlap=150)

    assert chunks == ["hello world foo"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/agents/contexthub/test_chunk.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement chunking**

Create `backend/src/agentdrops/agents/contexthub/__init__.py` (empty).

Create `backend/src/agentdrops/agents/contexthub/chunk.py`:

```python
"""Sliding-window text chunking for Context Hub ingestion — plain character-based windows,
no tokenizer dependency, since exact token boundaries don't matter for retrieval snippets."""


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split `text` into overlapping `chunk_size`-character windows. Whitespace (including
    newlines) is collapsed to single spaces first, so chunk boundaries never depend on a
    source document's original line-wrapping."""
    normalized = " ".join(text.split())
    if not normalized:
        return []

    step = chunk_size - overlap
    chunks = []
    start = 0
    while True:
        end = start + chunk_size
        chunks.append(normalized[start:end])
        if end >= len(normalized):
            break
        start += step
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/agents/contexthub/test_chunk.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing tests — extraction**

Create `backend/tests/unit/agents/contexthub/test_extract.py`:

```python
import io

import httpx
import pytest
from docx import Document
from pypdf import PdfWriter
from respx import MockRouter

from agentdrops.agents.contexthub.extract import extract_file_text, fetch_url_text


def test_extract_file_text_txt() -> None:
    assert extract_file_text("txt", b"hello world") == "hello world"


def test_extract_file_text_csv() -> None:
    assert extract_file_text("csv", b"a,b\n1,2") == "a,b\n1,2"


def test_extract_file_text_docx() -> None:
    document = Document()
    document.add_paragraph("First paragraph.")
    document.add_paragraph("Second paragraph.")
    buffer = io.BytesIO()
    document.save(buffer)

    text = extract_file_text("docx", buffer.getvalue())

    assert "First paragraph." in text
    assert "Second paragraph." in text


def test_extract_file_text_pdf() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    # A blank page extracts to empty text — this only proves the pdf path runs without error
    # and returns a string, not that it finds text on a page with none.
    assert extract_file_text("pdf", buffer.getvalue()) == ""


def test_extract_file_text_unsupported_type_raises() -> None:
    with pytest.raises(ValueError, match="unsupported content_type"):
        extract_file_text("exe", b"whatever")


@pytest.mark.respx(base_url="https://internal.example.com")
async def test_fetch_url_text_strips_html_tags(respx_mock: MockRouter) -> None:
    respx_mock.get("/page").mock(
        return_value=httpx.Response(
            200, text="<html><body><script>ignored</script><p>Hello <b>world</b></p></body></html>"
        )
    )
    async with httpx.AsyncClient(base_url="https://internal.example.com") as client:
        text = await fetch_url_text("https://internal.example.com/page", client)

    assert "Hello" in text
    assert "world" in text
    assert "ignored" not in text
    assert "<p>" not in text
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/agents/contexthub/test_extract.py -v`
Expected: FAIL — `extract.py` doesn't exist.

- [ ] **Step 7: Implement extraction**

Create `backend/src/agentdrops/agents/contexthub/extract.py`:

```python
"""Text extraction for Context Hub sources: pdf/docx/txt/csv files, and URL fetch + a minimal
stdlib HTML-to-text strip (no new HTML-parsing dependency)."""

import io
from html.parser import HTMLParser

import httpx
from docx import Document
from pypdf import PdfReader

from agentdrops.resilience.http_retry import HTTP_RETRY

_SKIP_TAGS = {"script", "style"}


class _TextExtractingParser(HTMLParser):
    """Collects text nodes outside `<script>`/`<style>`, joined with single spaces."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data.strip())

    def get_text(self) -> str:
        return " ".join(self._chunks)


def _extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def _extract_docx_text(data: bytes) -> str:
    document = Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


def extract_file_text(content_type: str, data: bytes) -> str:
    """Dispatch on the document's stored `content_type` (`pdf`/`docx`/`txt`/`csv`)."""
    if content_type == "pdf":
        return _extract_pdf_text(data)
    if content_type == "docx":
        return _extract_docx_text(data)
    if content_type in ("txt", "csv"):
        return data.decode("utf-8", errors="replace")
    raise ValueError(f"unsupported content_type: {content_type!r}")


@HTTP_RETRY
async def fetch_url_text(url: str, client: httpx.AsyncClient) -> str:
    response = await client.get(url)
    response.raise_for_status()
    parser = _TextExtractingParser()
    parser.feed(response.text)
    return parser.get_text()
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/agents/contexthub/test_extract.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/src/agentdrops/agents/contexthub backend/tests/unit/agents/contexthub
git commit -m "feat(contexthub): add content extraction and chunking"
```

---

## Task 5: Embedding client

**Files:**
- Create: `backend/src/agentdrops/agents/contexthub/embeddings.py`
- Test: `backend/tests/unit/agents/contexthub/test_embeddings.py`

**Interfaces:**
- Consumes: `Settings.embedding_api_key`, `Settings.embedding_base_url`, `Settings.embedding_model` (Task 1); `agentdrops.resilience.http_retry.HTTP_RETRY` (existing).
- Produces: `EmbeddingClient(api_key: str, base_url: str, model: str, client: httpx.AsyncClient)` with `async def embed(self, texts: list[str]) -> list[list[float]]` — Task 6's repository query and Task 7's search pipeline both depend on this exact signature, and Task 9's ingestion task constructs it directly.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/agents/contexthub/test_embeddings.py`:

```python
import httpx
import pytest
from respx import MockRouter

from agentdrops.agents.contexthub.embeddings import EmbeddingClient


@pytest.mark.respx(base_url="https://api.openai.com/v1")
async def test_embed_returns_one_vector_per_input_text(respx_mock: MockRouter) -> None:
    respx_mock.post("/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2]},
                    {"embedding": [0.3, 0.4]},
                ]
            },
        )
    )
    async with httpx.AsyncClient() as http_client:
        client = EmbeddingClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="text-embedding-3-small",
            client=http_client,
        )
        vectors = await client.embed(["hello", "world"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


async def test_embed_empty_input_returns_empty_list() -> None:
    async with httpx.AsyncClient() as http_client:
        client = EmbeddingClient(
            api_key="test-key", base_url="https://api.openai.com/v1",
            model="text-embedding-3-small", client=http_client,
        )
        assert await client.embed([]) == []


@pytest.mark.respx(base_url="https://api.openai.com/v1")
async def test_embed_sends_model_and_bearer_auth(respx_mock: MockRouter) -> None:
    route = respx_mock.post("/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
    )
    async with httpx.AsyncClient() as http_client:
        client = EmbeddingClient(
            api_key="secret-key", base_url="https://api.openai.com/v1",
            model="text-embedding-3-small", client=http_client,
        )
        await client.embed(["hi"])

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer secret-key"
    assert b'"model":"text-embedding-3-small"' in request.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/agents/contexthub/test_embeddings.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the embedding client**

Create `backend/src/agentdrops/agents/contexthub/embeddings.py`:

```python
"""Thin client for an OpenAI-wire-compatible /embeddings endpoint — independent of
agents/llm.py's chat-model dispatch, since embeddings aren't a chat-model call. Used both at
ingest time (embed each chunk) and at query time (embed the search query)."""

from typing import Any, cast

import httpx

from agentdrops.resilience.http_retry import HTTP_RETRY


class EmbeddingClient:
    def __init__(self, api_key: str, base_url: str, model: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = await self._call(texts)
        return [item["embedding"] for item in payload["data"]]

    @HTTP_RETRY
    async def _call(self, texts: list[str]) -> dict[str, Any]:
        response = await self._client.post(
            f"{self._base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": texts},
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/agents/contexthub/test_embeddings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/agentdrops/agents/contexthub/embeddings.py \
  backend/tests/unit/agents/contexthub/test_embeddings.py
git commit -m "feat(contexthub): add OpenAI-compatible embedding client"
```

---

## Task 6: Repository layer — `ContextHubStore`

**Files:**
- Create: `backend/src/agentdrops/repository/contexthub.py`
- Test: `backend/tests/unit/repository/test_contexthub.py`

**Interfaces:**
- Consumes: `ContextHubDocumentTable`, `ContextHubChunkTable` (Task 2); `tests/unit/repository/conftest.py::session_factory` (existing real-Postgres fixture).
- Produces: `ContextHubDocumentRecord` (dataclass: `id`, `title`, `source_type`, `source_name`, `content_type`, `status`, `error`, `minio_key`, `created_at`), `ContextHubChunkMatch` (dataclass: `document_id`, `document_title`, `content`, `distance`), and `ContextHubStore(session_factory)` with:
  - `async def create_document(self, *, title: str, source_type: str, source_name: str, content_type: str) -> ContextHubDocumentRecord`
  - `async def set_minio_key(self, document_id: str, minio_key: str) -> None`
  - `async def mark_ready(self, document_id: str) -> None`
  - `async def mark_failed(self, document_id: str, error: str) -> None`
  - `async def get_document(self, document_id: str) -> ContextHubDocumentRecord | None`
  - `async def list_documents(self) -> list[ContextHubDocumentRecord]`
  - `async def delete_document(self, document_id: str) -> bool`
  - `async def insert_chunks(self, document_id: str, chunks: list[str], embeddings: list[list[float]]) -> None`
  - `async def search_chunks(self, embedding: list[float], top_k: int) -> list[ContextHubChunkMatch]`

  Task 7 (search pipeline), Task 9 (service + ingestion task) both depend on these exact names.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/repository/test_contexthub.py`:

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.repository.contexthub import ContextHubStore


async def _truncate(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await session.execute(
            text("TRUNCATE contexthub_documents, contexthub_chunks RESTART IDENTITY CASCADE")
        )
        await session.commit()


async def test_create_document_defaults_to_processing_status(session_factory) -> None:
    await _truncate(session_factory)
    store = ContextHubStore(session_factory)

    doc = await store.create_document(
        title="report.pdf", source_type="file", source_name="report.pdf", content_type="pdf"
    )

    assert doc.status == "processing"
    assert doc.minio_key is None
    fetched = await store.get_document(doc.id)
    assert fetched == doc


async def test_mark_ready_then_mark_failed_updates_status(session_factory) -> None:
    await _truncate(session_factory)
    store = ContextHubStore(session_factory)
    doc = await store.create_document(
        title="x.txt", source_type="file", source_name="x.txt", content_type="txt"
    )

    await store.mark_ready(doc.id)
    assert (await store.get_document(doc.id)).status == "ready"

    await store.mark_failed(doc.id, "boom")
    refreshed = await store.get_document(doc.id)
    assert refreshed.status == "failed"
    assert refreshed.error == "boom"


async def test_list_documents_returns_newest_first(session_factory) -> None:
    await _truncate(session_factory)
    store = ContextHubStore(session_factory)
    first = await store.create_document(
        title="a.txt", source_type="file", source_name="a.txt", content_type="txt"
    )
    second = await store.create_document(
        title="b.txt", source_type="file", source_name="b.txt", content_type="txt"
    )

    docs = await store.list_documents()

    assert [d.id for d in docs] == [second.id, first.id]


async def test_delete_document_cascades_chunks(session_factory) -> None:
    await _truncate(session_factory)
    store = ContextHubStore(session_factory)
    doc = await store.create_document(
        title="x.txt", source_type="file", source_name="x.txt", content_type="txt"
    )
    await store.insert_chunks(doc.id, ["chunk one"], [[0.1] * 1536])

    deleted = await store.delete_document(doc.id)

    assert deleted is True
    assert await store.get_document(doc.id) is None
    matches = await store.search_chunks([0.1] * 1536, top_k=5)
    assert matches == []


async def test_delete_document_returns_false_when_unknown(session_factory) -> None:
    await _truncate(session_factory)
    store = ContextHubStore(session_factory)

    assert await store.delete_document("nonexistent") is False


async def test_search_chunks_only_returns_ready_documents_ranked_by_similarity(
    session_factory,
) -> None:
    await _truncate(session_factory)
    store = ContextHubStore(session_factory)

    ready = await store.create_document(
        title="ready.txt", source_type="file", source_name="ready.txt", content_type="txt"
    )
    await store.insert_chunks(ready.id, ["close match"], [[1.0, 0.0] + [0.0] * 1534])
    await store.mark_ready(ready.id)

    processing = await store.create_document(
        title="processing.txt", source_type="file", source_name="processing.txt",
        content_type="txt",
    )
    await store.insert_chunks(processing.id, ["should not appear"], [[1.0, 0.0] + [0.0] * 1534])
    # left in "processing" status deliberately — must be excluded from search results

    matches = await store.search_chunks([1.0, 0.0] + [0.0] * 1534, top_k=5)

    assert len(matches) == 1
    assert matches[0].document_id == ready.id
    assert matches[0].document_title == "ready.txt"
    assert matches[0].content == "close match"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/repository/test_contexthub.py -v`
Expected: FAIL (or SKIPPED if Postgres isn't running — start it first: `docker compose up -d postgres` from Task 1, then `alembic upgrade head` from Task 2).

- [ ] **Step 3: Implement the repository**

Create `backend/src/agentdrops/repository/contexthub.py`:

```python
"""Postgres-backed Context Hub document/chunk registry: CRUD for uploaded documents plus
pgvector cosine-similarity search over their chunks. Global (no thread_id) — see
db/migrations/versions/0006_add_contexthub_tables.py for the schema."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.db.models import ContextHubChunkTable, ContextHubDocumentTable

Status = Literal["processing", "ready", "failed"]


@dataclass
class ContextHubDocumentRecord:
    id: str
    title: str
    source_type: str
    source_name: str
    content_type: str
    status: Status
    created_at: datetime
    error: str | None = None
    minio_key: str | None = None


@dataclass
class ContextHubChunkMatch:
    document_id: str
    document_title: str
    content: str
    distance: float


def _to_record(row: ContextHubDocumentTable) -> ContextHubDocumentRecord:
    return ContextHubDocumentRecord(
        id=row.id,
        title=row.title,
        source_type=row.source_type,
        source_name=row.source_name,
        content_type=row.content_type,
        status=row.status,  # type: ignore[arg-type]
        created_at=row.created_at,
        error=row.error,
        minio_key=row.minio_key,
    )


class ContextHubStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_document(
        self, *, title: str, source_type: str, source_name: str, content_type: str
    ) -> ContextHubDocumentRecord:
        async with self._session_factory() as session:
            row = ContextHubDocumentTable(
                id=str(uuid.uuid4()),
                title=title,
                source_type=source_type,
                source_name=source_name,
                content_type=content_type,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_record(row)

    async def set_minio_key(self, document_id: str, minio_key: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(ContextHubDocumentTable)
                .where(ContextHubDocumentTable.id == document_id)
                .values(minio_key=minio_key)
            )
            await session.commit()

    async def mark_ready(self, document_id: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(ContextHubDocumentTable)
                .where(ContextHubDocumentTable.id == document_id)
                .values(status="ready", error=None)
            )
            await session.commit()

    async def mark_failed(self, document_id: str, error: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(ContextHubDocumentTable)
                .where(ContextHubDocumentTable.id == document_id)
                .values(status="failed", error=error)
            )
            await session.commit()

    async def get_document(self, document_id: str) -> ContextHubDocumentRecord | None:
        async with self._session_factory() as session:
            row = await session.get(ContextHubDocumentTable, document_id)
            return _to_record(row) if row is not None else None

    async def list_documents(self) -> list[ContextHubDocumentRecord]:
        async with self._session_factory() as session:
            stmt = select(ContextHubDocumentTable).order_by(
                ContextHubDocumentTable.created_at.desc()
            )
            result = await session.execute(stmt)
            return [_to_record(row) for row in result.scalars().all()]

    async def delete_document(self, document_id: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(ContextHubDocumentTable)
                .where(ContextHubDocumentTable.id == document_id)
                .returning(ContextHubDocumentTable.id)
            )
            deleted = result.scalar_one_or_none() is not None
            await session.commit()
            return deleted

    async def insert_chunks(
        self, document_id: str, chunks: list[str], embeddings: list[list[float]]
    ) -> None:
        async with self._session_factory() as session:
            rows = [
                ContextHubChunkTable(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    chunk_index=index,
                    content=content,
                    embedding=embedding,
                )
                for index, (content, embedding) in enumerate(zip(chunks, embeddings, strict=True))
            ]
            session.add_all(rows)
            await session.commit()

    async def search_chunks(self, embedding: list[float], top_k: int) -> list[ContextHubChunkMatch]:
        async with self._session_factory() as session:
            distance = ContextHubChunkTable.embedding.cosine_distance(embedding)
            stmt = (
                select(
                    ContextHubChunkTable.document_id,
                    ContextHubDocumentTable.title,
                    ContextHubChunkTable.content,
                    distance.label("distance"),
                )
                .join(
                    ContextHubDocumentTable,
                    ContextHubChunkTable.document_id == ContextHubDocumentTable.id,
                )
                .where(ContextHubDocumentTable.status == "ready")
                .order_by(distance)
                .limit(top_k)
            )
            result = await session.execute(stmt)
            return [
                ContextHubChunkMatch(
                    document_id=row.document_id,
                    document_title=row.title,
                    content=row.content,
                    distance=row.distance,
                )
                for row in result.all()
            ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/repository/test_contexthub.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/agentdrops/repository/contexthub.py backend/tests/unit/repository/test_contexthub.py
git commit -m "feat(contexthub): add ContextHubStore repository (CRUD + vector search)"
```

---

## Task 7: Search pipeline and the `context_hub_search` tool

**Files:**
- Create: `backend/src/agentdrops/agents/contexthub/methods.py`
- Create: `backend/src/agentdrops/agents/contexthub/tools.py`
- Test: `backend/tests/unit/agents/contexthub/test_methods.py`
- Test: `backend/tests/unit/agents/contexthub/test_tools.py`

**Interfaces:**
- Consumes: `EmbeddingClient.embed` (Task 5), `ContextHubStore.search_chunks` → `ContextHubChunkMatch` (Task 6).
- Produces: `format_contexthub_output(matches: list[ContextHubChunkMatch]) -> str`, `async def run_contexthub_search_pipeline(store, embedder, query: str, top_k: int) -> str`, `make_context_hub_tool(store, embedder, top_k: int) -> BaseTool` (tool name: `context_hub_search`) — Task 8's graph wiring depends on `make_context_hub_tool`'s exact signature and the tool name.

- [ ] **Step 1: Write the failing test — search pipeline**

Create `backend/tests/unit/agents/contexthub/test_methods.py`:

```python
from unittest.mock import AsyncMock

from agentdrops.agents.contexthub.methods import (
    format_contexthub_output,
    run_contexthub_search_pipeline,
)
from agentdrops.repository.contexthub import ContextHubChunkMatch


def test_format_contexthub_output_empty() -> None:
    assert format_contexthub_output([]) == "No relevant internal knowledge found."


def test_format_contexthub_output_renders_document_and_excerpt() -> None:
    matches = [
        ContextHubChunkMatch(
            document_id="d1", document_title="Q3 Report", content="revenue grew 12%",
            distance=0.1,
        )
    ]

    output = format_contexthub_output(matches)

    assert "Q3 Report" in output
    assert "revenue grew 12%" in output


async def test_run_contexthub_search_pipeline_embeds_query_and_formats_matches() -> None:
    embedder = AsyncMock()
    embedder.embed.return_value = [[0.1, 0.2]]
    store = AsyncMock()
    store.search_chunks.return_value = [
        ContextHubChunkMatch(
            document_id="d1", document_title="Q3 Report", content="revenue grew 12%",
            distance=0.1,
        )
    ]

    result = await run_contexthub_search_pipeline(store, embedder, "revenue growth", top_k=5)

    embedder.embed.assert_awaited_once_with(["revenue growth"])
    store.search_chunks.assert_awaited_once_with([0.1, 0.2], 5)
    assert "Q3 Report" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/agents/contexthub/test_methods.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the search pipeline**

Create `backend/src/agentdrops/agents/contexthub/methods.py`:

```python
"""Context Hub retrieval pipeline: embed the query, vector-search chunks, format for the
agent — the Context Hub counterpart of agents/research/methods.py::run_search_pipeline."""

from agentdrops.agents.contexthub.embeddings import EmbeddingClient
from agentdrops.repository.contexthub import ContextHubChunkMatch, ContextHubStore


def format_contexthub_output(matches: list[ContextHubChunkMatch]) -> str:
    if not matches:
        return "No relevant internal knowledge found."
    blocks = [
        f"DOCUMENT {i}: {match.document_title}\nEXCERPT: {match.content}"
        for i, match in enumerate(matches, start=1)
    ]
    return "\n\n".join(blocks)


async def run_contexthub_search_pipeline(
    store: ContextHubStore, embedder: EmbeddingClient, query: str, top_k: int
) -> str:
    [query_embedding] = await embedder.embed([query])
    matches = await store.search_chunks(query_embedding, top_k)
    return format_contexthub_output(matches)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/agents/contexthub/test_methods.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test — the tool**

Create `backend/tests/unit/agents/contexthub/test_tools.py`:

```python
from unittest.mock import AsyncMock, patch

from agentdrops.agents.contexthub.tools import make_context_hub_tool


async def test_context_hub_search_tool_calls_the_search_pipeline() -> None:
    store = AsyncMock()
    embedder = AsyncMock()
    tool = make_context_hub_tool(store, embedder, top_k=3)

    assert tool.name == "context_hub_search"

    with patch(
        "agentdrops.agents.contexthub.tools.run_contexthub_search_pipeline",
        AsyncMock(return_value="DOCUMENT 1: ..."),
    ) as pipeline:
        result = await tool.ainvoke({"query": "pricing strategy"})

    pipeline.assert_awaited_once_with(store, embedder, "pricing strategy", 3)
    assert result == "DOCUMENT 1: ..."
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/agents/contexthub/test_tools.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 7: Implement the tool**

Create `backend/src/agentdrops/agents/contexthub/tools.py`:

```python
"""Adapts the Context Hub search pipeline into a LangChain tool, the same shape as
agents/tools.py::make_tavily_tool."""

from langchain_core.tools import BaseTool, tool

from agentdrops.agents.contexthub.embeddings import EmbeddingClient
from agentdrops.agents.contexthub.methods import run_contexthub_search_pipeline
from agentdrops.repository.contexthub import ContextHubStore


def make_context_hub_tool(
    store: ContextHubStore, embedder: EmbeddingClient, top_k: int
) -> BaseTool:
    @tool
    async def context_hub_search(query: str) -> str:
        """Search uploaded enterprise documents and URLs (Context Hub) for content relevant
        to `query`. Only available when the user has opted in for this research turn."""
        return await run_contexthub_search_pipeline(store, embedder, query, top_k)

    return context_hub_search
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/agents/contexthub/test_tools.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/src/agentdrops/agents/contexthub/methods.py backend/src/agentdrops/agents/contexthub/tools.py \
  backend/tests/unit/agents/contexthub/test_methods.py backend/tests/unit/agents/contexthub/test_tools.py
git commit -m "feat(contexthub): add search pipeline and context_hub_search tool"
```

---

## Task 8: Graph wiring — per-turn `use_context_hub` toggle

**Files:**
- Modify: `backend/src/agentdrops/agents/graph.py`
- Modify: `backend/tests/unit/agents/test_graph.py`

**Interfaces:**
- Consumes: `make_context_hub_tool` (Task 7), `ContextHubStore` (Task 6), `EmbeddingClient` (Task 5).
- Produces: `build_market_researcher(settings, client, checkpointer, session_factory=None, *, use_context_hub=False)` — Task 9's ingestion task doesn't call this; Task 11's `worker/tasks.py` threading does, with the exact keyword names `session_factory` and `use_context_hub`.

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/agents/test_graph.py` already exists with one test (`test_build_market_researcher_compiles_with_the_given_checkpointer`, calling `build_market_researcher(make_settings(), client, checkpointer)` with 3 positional args — this must keep passing unchanged, since it's the "no Context Hub" default path). Append these two tests to that file, reusing its existing `httpx`/`InMemorySaver`/`build_market_researcher`/`make_settings` imports:

```python
async def test_use_context_hub_true_adds_context_hub_search_tool(monkeypatch) -> None:
    captured_tools = {}

    def fake_build_research_graph(settings, tools):
        captured_tools["tools"] = tools
        from agentdrops.agents.research.graph import build_research_graph as real
        return real(settings, tools)

    monkeypatch.setattr(
        "agentdrops.agents.graph.build_research_graph", fake_build_research_graph
    )
    settings = make_settings()
    async with httpx.AsyncClient() as client:
        build_market_researcher(
            settings, client, InMemorySaver(),
            session_factory=object(), use_context_hub=True,
        )

    tool_names = {t.name for t in captured_tools["tools"]}
    assert "context_hub_search" in tool_names


async def test_use_context_hub_true_without_session_factory_raises() -> None:
    settings = make_settings()
    async with httpx.AsyncClient() as client:
        try:
            build_market_researcher(settings, client, InMemorySaver(), use_context_hub=True)
            raised = False
        except AssertionError:
            raised = True
    assert raised
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/agents/test_graph.py -v`
Expected: The two new tests FAIL — `build_market_researcher` doesn't accept `session_factory`/`use_context_hub` yet. The pre-existing test still passes.

- [ ] **Step 3: Wire the tool into the graph**

In `backend/src/agentdrops/agents/graph.py`, update imports and the function signature/body:

```python
from typing import Any, cast

import httpx
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.agents.contexthub.embeddings import EmbeddingClient
from agentdrops.agents.contexthub.tools import make_context_hub_tool
from agentdrops.agents.llm import build_llm
from agentdrops.agents.research.graph import build_research_graph
from agentdrops.agents.scope.graph import build_scope_nodes, route_after_clarify
from agentdrops.agents.state import AgentState, SupervisorState
from agentdrops.agents.supervisor.graph import build_supervisor_graph, get_notes_from_tool_calls
from agentdrops.agents.tools import make_tavily_tool, think_tool
from agentdrops.agents.writer.graph import build_writer_node
from agentdrops.config import Settings
from agentdrops.repository.contexthub import ContextHubStore
from agentdrops.webtools.tavily import TavilySearchTool


def build_market_researcher(
    settings: Settings,
    client: httpx.AsyncClient,
    checkpointer: BaseCheckpointSaver[Any],
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    *,
    use_context_hub: bool = False,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the full market-research pipeline. `tavily_search`/`think_tool` are always
    available; `context_hub_search` is included only when `use_context_hub` is True (a
    per-turn opt-in — see worker/tasks.py), which requires `session_factory` to build its
    `ContextHubStore`.
    """
    tavily = TavilySearchTool(api_key=settings.tavily_api_key, client=client)
    summarizer_llm = build_llm(settings)
    tavily_search = make_tavily_tool(tavily, summarizer_llm)
    tools: list[Any] = [tavily_search, think_tool]

    if use_context_hub:
        assert session_factory is not None, "use_context_hub=True requires a session_factory"
        contexthub_store = ContextHubStore(session_factory)
        embedder = EmbeddingClient(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            client=client,
        )
        tools.append(
            make_context_hub_tool(contexthub_store, embedder, top_k=settings.contexthub_search_top_k)
        )

    research_graph = build_research_graph(settings, tools=tools)
    supervisor_graph = build_supervisor_graph(settings, research_graph)
    clarify_with_user, write_research_brief = build_scope_nodes(settings)
    final_report_generation = build_writer_node(settings)
    # ... rest of the function (supervisor node, graph wiring) is unchanged
```

(Leave the `supervisor` node closure and the `StateGraph`/`add_node`/`add_edge` wiring below it exactly as-is — only the top of the function changes.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/agents/test_graph.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend test suite to check nothing else broke**

Run: `cd backend && pytest -v`
Expected: PASS (existing callers of `build_market_researcher` in `main.py`/`worker/tasks.py` still call it with 3 positional args, which still works since `session_factory` defaults to `None` and `use_context_hub` defaults to `False`).

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/agents/graph.py backend/tests/unit/agents/test_graph.py
git commit -m "feat(contexthub): wire context_hub_search into the graph behind a per-turn flag"
```

---

## Task 9: Ingestion service and Celery task

**Files:**
- Create: `backend/src/agentdrops/service/contexthub_service.py`
- Modify: `backend/src/agentdrops/worker/tasks.py`
- Test: `backend/tests/unit/service/test_contexthub_service.py`
- Test: `backend/tests/unit/worker/test_tasks.py` (add to existing file)

**Interfaces:**
- Consumes: `ContextHubStore` (Task 6), `ContextHubStorage` (Task 3), `extract_file_text`/`fetch_url_text`/`chunk_text` (Task 4), `EmbeddingClient` (Task 5).
- Produces: `ContextHubService(store, storage)` with `async def upload_file(self, filename: str, content_type: str, data: bytes) -> ContextHubDocumentRecord`, `async def add_url(self, url: str) -> ContextHubDocumentRecord`, `async def list_documents(self) -> list[ContextHubDocumentRecord]`, `async def delete_document(self, document_id: str) -> Literal["deleted", "not_found"]` — Task 10's router depends on this exact interface. Also produces Celery task `agentdrops.ingest_contexthub_document` (`ingest_contexthub_document_task(document_id: str) -> None`), which `ContextHubService.upload_file`/`add_url` enqueue via `.delay(...)`.

- [ ] **Step 1: Write the failing test — service**

Create `backend/tests/unit/service/test_contexthub_service.py`:

```python
from unittest.mock import AsyncMock, patch

from agentdrops.repository.contexthub import ContextHubDocumentRecord
from agentdrops.service.contexthub_service import ContextHubService


def _make_record(**overrides) -> ContextHubDocumentRecord:
    from datetime import UTC, datetime

    defaults = dict(
        id="doc-1", title="report.pdf", source_type="file", source_name="report.pdf",
        content_type="pdf", status="processing", created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return ContextHubDocumentRecord(**defaults)


async def test_upload_file_stores_bytes_and_enqueues_ingestion() -> None:
    store = AsyncMock()
    store.create_document.return_value = _make_record()
    storage = AsyncMock()
    service = ContextHubService(store, storage)

    with patch(
        "agentdrops.service.contexthub_service.ingest_contexthub_document_task"
    ) as task:
        doc = await service.upload_file("report.pdf", "pdf", b"file bytes")

    store.create_document.assert_awaited_once_with(
        title="report.pdf", source_type="file", source_name="report.pdf", content_type="pdf"
    )
    storage.put.assert_awaited_once_with("doc-1/report.pdf", b"file bytes", "application/pdf")
    store.set_minio_key.assert_awaited_once_with("doc-1", "doc-1/report.pdf")
    task.delay.assert_called_once_with("doc-1")
    assert doc.id == "doc-1"


async def test_add_url_skips_storage_and_enqueues_ingestion() -> None:
    store = AsyncMock()
    store.create_document.return_value = _make_record(
        source_type="url", source_name="https://intranet.example.com/wiki", content_type="url"
    )
    storage = AsyncMock()
    service = ContextHubService(store, storage)

    with patch(
        "agentdrops.service.contexthub_service.ingest_contexthub_document_task"
    ) as task:
        await service.add_url("https://intranet.example.com/wiki")

    store.create_document.assert_awaited_once_with(
        title="https://intranet.example.com/wiki", source_type="url",
        source_name="https://intranet.example.com/wiki", content_type="url",
    )
    storage.put.assert_not_awaited()
    task.delay.assert_called_once_with("doc-1")


async def test_delete_document_removes_storage_object_when_present() -> None:
    store = AsyncMock()
    store.get_document.return_value = _make_record(minio_key="doc-1/report.pdf")
    store.delete_document.return_value = True
    storage = AsyncMock()
    service = ContextHubService(store, storage)

    result = await service.delete_document("doc-1")

    storage.delete.assert_awaited_once_with("doc-1/report.pdf")
    store.delete_document.assert_awaited_once_with("doc-1")
    assert result == "deleted"


async def test_delete_document_not_found() -> None:
    store = AsyncMock()
    store.get_document.return_value = None
    storage = AsyncMock()
    service = ContextHubService(store, storage)

    assert await service.delete_document("missing") == "not_found"
    storage.delete.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/service/test_contexthub_service.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the service**

Create `backend/src/agentdrops/service/contexthub_service.py`:

```python
"""Context Hub business logic: upload/list/delete orchestration. Routers only extract request
data and call into this — see api/v1/contexthub.py."""

from typing import Literal

from agentdrops.repository.contexthub import ContextHubDocumentRecord, ContextHubStore
from agentdrops.storage.contexthub import ContextHubStorage
from agentdrops.worker.tasks import ingest_contexthub_document_task

_CONTENT_TYPE_MIME: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "csv": "text/csv",
}

DeleteResult = Literal["deleted", "not_found"]


class ContextHubService:
    def __init__(self, store: ContextHubStore, storage: ContextHubStorage) -> None:
        self._store = store
        self._storage = storage

    async def upload_file(
        self, filename: str, content_type: str, data: bytes
    ) -> ContextHubDocumentRecord:
        document = await self._store.create_document(
            title=filename, source_type="file", source_name=filename, content_type=content_type
        )
        minio_key = f"{document.id}/{filename}"
        await self._storage.put(minio_key, data, _CONTENT_TYPE_MIME[content_type])
        await self._store.set_minio_key(document.id, minio_key)
        ingest_contexthub_document_task.delay(document.id)
        return document

    async def add_url(self, url: str) -> ContextHubDocumentRecord:
        document = await self._store.create_document(
            title=url, source_type="url", source_name=url, content_type="url"
        )
        ingest_contexthub_document_task.delay(document.id)
        return document

    async def list_documents(self) -> list[ContextHubDocumentRecord]:
        return await self._store.list_documents()

    async def delete_document(self, document_id: str) -> DeleteResult:
        document = await self._store.get_document(document_id)
        if document is None:
            return "not_found"
        if document.minio_key is not None:
            await self._storage.delete(document.minio_key)
        await self._store.delete_document(document_id)
        return "deleted"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/service/test_contexthub_service.py -v`
Expected: FAIL still — `ingest_contexthub_document_task` doesn't exist in `worker/tasks.py` yet; continue to the next step before re-running.

- [ ] **Step 5: Write the failing test — ingestion task**

Add to `backend/tests/unit/worker/test_tasks.py` (same file as `run_turn_task`'s tests — reuse its `patch_worker_dependencies` fixture where it applies, and follow its `_Fake*`/`_Recording*` naming style):

```python
class _FakeContextHubStore:
    def __init__(self) -> None:
        self.ready_ids: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.inserted: list[tuple[str, list[str], list[list[float]]]] = []
        self._document = None

    def set_document(self, document) -> None:
        self._document = document

    async def get_document(self, document_id: str):
        return self._document

    async def insert_chunks(self, document_id, chunks, embeddings) -> None:
        self.inserted.append((document_id, chunks, embeddings))

    async def mark_ready(self, document_id: str) -> None:
        self.ready_ids.append(document_id)

    async def mark_failed(self, document_id: str, error: str) -> None:
        self.failed.append((document_id, error))


class _FakeContextHubStorage:
    def __init__(self, data: bytes = b"hello world") -> None:
        self._data = data

    async def get(self, key: str) -> bytes:
        return self._data


def test_ingest_contexthub_document_task_extracts_chunks_and_embeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from agentdrops.repository.contexthub import ContextHubDocumentRecord

    fake_store = _FakeContextHubStore()
    fake_store.set_document(
        ContextHubDocumentRecord(
            id="doc-1", title="a.txt", source_type="file", source_name="a.txt",
            content_type="txt", status="processing", created_at=datetime.now(UTC),
            minio_key="doc-1/a.txt",
        )
    )
    monkeypatch.setattr(tasks_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(tasks_module, "create_engine", lambda settings: _FakeEngine())
    monkeypatch.setattr(tasks_module, "create_session_factory", lambda engine: object())
    monkeypatch.setattr(tasks_module, "ContextHubStore", lambda session_factory: fake_store)
    monkeypatch.setattr(
        tasks_module, "ContextHubStorage", lambda settings: _FakeContextHubStorage()
    )

    class _FakeEmbedder:
        def __init__(self, **_kwargs) -> None:
            pass

        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * 1536 for _ in texts]

    monkeypatch.setattr(tasks_module, "EmbeddingClient", _FakeEmbedder)

    tasks_module.ingest_contexthub_document_task("doc-1")

    assert fake_store.ready_ids == ["doc-1"]
    assert fake_store.inserted[0][0] == "doc-1"
    assert fake_store.inserted[0][1] == ["hello world"]


def test_ingest_contexthub_document_task_marks_failed_on_extraction_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from agentdrops.repository.contexthub import ContextHubDocumentRecord

    fake_store = _FakeContextHubStore()
    fake_store.set_document(
        ContextHubDocumentRecord(
            id="doc-2", title="a.exe", source_type="file", source_name="a.exe",
            content_type="exe", status="processing", created_at=datetime.now(UTC),
            minio_key="doc-2/a.exe",
        )
    )
    monkeypatch.setattr(tasks_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(tasks_module, "create_engine", lambda settings: _FakeEngine())
    monkeypatch.setattr(tasks_module, "create_session_factory", lambda engine: object())
    monkeypatch.setattr(tasks_module, "ContextHubStore", lambda session_factory: fake_store)
    monkeypatch.setattr(
        tasks_module, "ContextHubStorage", lambda settings: _FakeContextHubStorage()
    )

    tasks_module.ingest_contexthub_document_task("doc-2")

    assert fake_store.ready_ids == []
    assert fake_store.failed[0][0] == "doc-2"
    assert "unsupported content_type" in fake_store.failed[0][1]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/worker/test_tasks.py -v`
Expected: FAIL — `ingest_contexthub_document_task` doesn't exist yet.

- [ ] **Step 7: Implement the ingestion task**

In `backend/src/agentdrops/worker/tasks.py`, add these imports alongside the existing ones:

```python
from agentdrops.agents.contexthub.chunk import chunk_text
from agentdrops.agents.contexthub.embeddings import EmbeddingClient
from agentdrops.agents.contexthub.extract import extract_file_text, fetch_url_text
from agentdrops.repository.contexthub import ContextHubStore
from agentdrops.storage.contexthub import ContextHubStorage
```

Add this new function and task at the end of the file:

```python
async def _execute_ingest(document_id: str, settings: Settings) -> None:
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        store = ContextHubStore(session_factory)
        storage = ContextHubStorage(settings)
        async with httpx.AsyncClient(timeout=30.0) as client:
            embedder = EmbeddingClient(
                api_key=settings.embedding_api_key,
                base_url=settings.embedding_base_url,
                model=settings.embedding_model,
                client=client,
            )
            try:
                document = await store.get_document(document_id)
                assert document is not None, f"unknown contexthub document_id={document_id}"

                if document.source_type == "url":
                    text = await fetch_url_text(document.source_name, client)
                else:
                    assert document.minio_key is not None
                    raw = await storage.get(document.minio_key)
                    text = extract_file_text(document.content_type, raw)

                chunks = chunk_text(
                    text, settings.contexthub_chunk_size, settings.contexthub_chunk_overlap
                )
                embeddings = await embedder.embed(chunks)
                await store.insert_chunks(document.id, chunks, embeddings)
                await store.mark_ready(document.id)
            except Exception as exc:
                logger.exception("contexthub ingestion failed for document_id=%s", document_id)
                await store.mark_failed(document_id, str(exc))
    finally:
        await engine.dispose()


@celery_app.task(name="agentdrops.ingest_contexthub_document")  # type: ignore[untyped-decorator]
def ingest_contexthub_document_task(document_id: str) -> None:
    asyncio.run(_execute_ingest(document_id, get_settings()))
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/worker/test_tasks.py tests/unit/service/test_contexthub_service.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/src/agentdrops/service/contexthub_service.py backend/src/agentdrops/worker/tasks.py \
  backend/tests/unit/service/test_contexthub_service.py backend/tests/unit/worker/test_tasks.py
git commit -m "feat(contexthub): add ingestion service and Celery ingestion task"
```

---

## Task 10: API router, schema, and app wiring

**Files:**
- Modify: `backend/src/agentdrops/api/v1/schema.py`
- Create: `backend/src/agentdrops/api/v1/contexthub.py`
- Modify: `backend/src/agentdrops/api/v1/__init__.py`
- Modify: `backend/src/agentdrops/main.py`
- Test: `backend/tests/unit/api/v1/test_contexthub.py`

**Interfaces:**
- Consumes: `ContextHubService` (Task 9).
- Produces: `POST /v1/contexthub/documents`, `POST /v1/contexthub/urls`, `GET /v1/contexthub/documents`, `DELETE /v1/contexthub/documents/{id}`; `app.state.contexthub_service`.

- [ ] **Step 1: Add request/response schemas**

In `backend/src/agentdrops/api/v1/schema.py`, add:

```python
from pydantic import HttpUrl  # add to the existing pydantic import line


class ContextHubUrlRequest(BaseModel):
    url: HttpUrl


class ContextHubDocumentResponse(BaseModel):
    id: str
    title: str
    source_type: Literal["file", "url"]
    status: Literal["processing", "ready", "failed"]
    error: str | None = None
    created_at: str


class ContextHubDocumentsResponse(BaseModel):
    documents: list[ContextHubDocumentResponse]
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/unit/api/v1/test_contexthub.py`:

```python
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agentdrops.repository.contexthub import ContextHubDocumentRecord


def _make_record(**overrides) -> ContextHubDocumentRecord:
    defaults = dict(
        id="doc-1", title="report.pdf", source_type="file", source_name="report.pdf",
        content_type="pdf", status="processing", created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return ContextHubDocumentRecord(**defaults)


@pytest.fixture
def contexthub_service(client: TestClient) -> AsyncMock:
    service = AsyncMock()
    client.app.state.contexthub_service = service
    return service


def test_upload_document_returns_the_created_record(
    client: TestClient, contexthub_service: AsyncMock
) -> None:
    contexthub_service.upload_file.return_value = _make_record()

    response = client.post(
        "/v1/contexthub/documents",
        files={"file": ("report.pdf", b"file bytes", "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["id"] == "doc-1"
    assert body["status"] == "processing"
    contexthub_service.upload_file.assert_awaited_once_with("report.pdf", "pdf", b"file bytes")


def test_upload_document_rejects_unsupported_extension(
    client: TestClient, contexthub_service: AsyncMock
) -> None:
    response = client.post(
        "/v1/contexthub/documents",
        files={"file": ("virus.exe", b"bytes", "application/octet-stream")},
    )

    assert response.status_code == 400
    contexthub_service.upload_file.assert_not_awaited()


def test_add_url_returns_the_created_record(
    client: TestClient, contexthub_service: AsyncMock
) -> None:
    contexthub_service.add_url.return_value = _make_record(
        source_type="url", source_name="https://intranet.example.com/wiki", content_type="url"
    )

    response = client.post(
        "/v1/contexthub/urls", json={"url": "https://intranet.example.com/wiki"}
    )

    assert response.status_code == 201
    contexthub_service.add_url.assert_awaited_once_with("https://intranet.example.com/wiki")


def test_list_documents_returns_all_records(
    client: TestClient, contexthub_service: AsyncMock
) -> None:
    contexthub_service.list_documents.return_value = [_make_record(status="ready")]

    response = client.get("/v1/contexthub/documents")

    assert response.status_code == 200
    documents = response.json()["data"]["documents"]
    assert len(documents) == 1
    assert documents[0]["status"] == "ready"


def test_delete_document_returns_404_when_unknown(
    client: TestClient, contexthub_service: AsyncMock
) -> None:
    contexthub_service.delete_document.return_value = "not_found"

    response = client.delete("/v1/contexthub/documents/missing")

    assert response.status_code == 404


def test_delete_document_returns_204_on_success(
    client: TestClient, contexthub_service: AsyncMock
) -> None:
    contexthub_service.delete_document.return_value = "deleted"

    response = client.delete("/v1/contexthub/documents/doc-1")

    assert response.status_code == 204
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/api/v1/test_contexthub.py -v`
Expected: FAIL — router doesn't exist yet.

- [ ] **Step 4: Implement the router**

Create `backend/src/agentdrops/api/v1/contexthub.py`:

```python
"""Context Hub endpoints: upload files/URLs into the global knowledge base, list, and delete."""

from fastapi import APIRouter, Request, UploadFile, status

from agentdrops.api.v1.schema import (
    ContextHubDocumentResponse,
    ContextHubDocumentsResponse,
    ContextHubUrlRequest,
)
from agentdrops.repository.contexthub import ContextHubDocumentRecord
from agentdrops.service.contexthub_service import ContextHubService
from agentdrops.types.error_codes import (
    BadRequestError,
    NotFoundError,
    fastAPIErrorResponseModels,
)
from agentdrops.types.response import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/contexthub", tags=["contexthub"])

_EXTENSION_CONTENT_TYPE: dict[str, str] = {
    "pdf": "pdf",
    "docx": "docx",
    "txt": "txt",
    "csv": "csv",
}


def _resolve_content_type(filename: str | None) -> str | None:
    if not filename or "." not in filename:
        return None
    return _EXTENSION_CONTENT_TYPE.get(filename.rsplit(".", 1)[-1].lower())


def _to_response(document: ContextHubDocumentRecord) -> ContextHubDocumentResponse:
    return ContextHubDocumentResponse(
        id=document.id,
        title=document.title,
        source_type=document.source_type,  # type: ignore[arg-type]
        status=document.status,
        error=document.error,
        created_at=document.created_at.isoformat(),
    )


@router.post(
    "/documents",
    response_model=SuccessResponse[ContextHubDocumentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file into Context Hub",
    responses={status.HTTP_400_BAD_REQUEST: fastAPIErrorResponseModels[status.HTTP_400_BAD_REQUEST]},
)
async def upload_document(
    request: Request, file: UploadFile
) -> SuccessResponse[ContextHubDocumentResponse]:
    content_type = _resolve_content_type(file.filename)
    if content_type is None:
        raise ErrorResponse(
            BadRequestError(message="Unsupported file type — allowed: pdf, docx, txt, csv")
        )
    data = await file.read()
    service: ContextHubService = request.app.state.contexthub_service
    document = await service.upload_file(file.filename or "upload", content_type, data)
    return SuccessResponse(data=_to_response(document))


@router.post(
    "/urls",
    response_model=SuccessResponse[ContextHubDocumentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Add a URL into Context Hub",
)
async def add_url(
    request: Request, body: ContextHubUrlRequest
) -> SuccessResponse[ContextHubDocumentResponse]:
    service: ContextHubService = request.app.state.contexthub_service
    document = await service.add_url(str(body.url))
    return SuccessResponse(data=_to_response(document))


@router.get(
    "/documents",
    response_model=SuccessResponse[ContextHubDocumentsResponse],
    summary="List Context Hub documents",
)
async def list_documents(request: Request) -> SuccessResponse[ContextHubDocumentsResponse]:
    service: ContextHubService = request.app.state.contexthub_service
    documents = await service.list_documents()
    return SuccessResponse(
        data=ContextHubDocumentsResponse(documents=[_to_response(d) for d in documents])
    )


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a Context Hub document",
    responses={status.HTTP_404_NOT_FOUND: fastAPIErrorResponseModels[status.HTTP_404_NOT_FOUND]},
)
async def delete_document(request: Request, document_id: str) -> None:
    service: ContextHubService = request.app.state.contexthub_service
    result = await service.delete_document(document_id)
    if result == "not_found":
        raise ErrorResponse(NotFoundError(message="Unknown document_id"))
```

Update `backend/src/agentdrops/api/v1/__init__.py`:

```python
from agentdrops.api.v1.contexthub import router as contexthub_router
# ... existing imports ...

router.include_router(chat_router)
router.include_router(contexthub_router)
router.include_router(sessions_router)
router.include_router(research_router)
router.include_router(suggestions_router)
```

- [ ] **Step 5: Wire services into `main.py`'s lifespan**

In `backend/src/agentdrops/main.py`, add imports:

```python
from agentdrops.repository.contexthub import ContextHubStore
from agentdrops.service.contexthub_service import ContextHubService
from agentdrops.storage.contexthub import ContextHubStorage
```

Inside `lifespan(...)`, after the existing `session_factory = create_session_factory(engine)` line, add:

```python
                contexthub_store = ContextHubStore(session_factory)
                contexthub_storage = ContextHubStorage(settings)
                app.state.contexthub_service = ContextHubService(contexthub_store, contexthub_storage)
```

(placed alongside the other `app.state.*_service` assignments already there)

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/api/v1/test_contexthub.py -v`
Expected: PASS. The `client` fixture used above already comes from `tests/unit/api/v1/conftest.py` (Task 10's test reuses that existing fixture, just adds `app.state.contexthub_service`).

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && pytest -v && ruff check . && mypy src`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/src/agentdrops/api/v1/schema.py backend/src/agentdrops/api/v1/contexthub.py \
  backend/src/agentdrops/api/v1/__init__.py backend/src/agentdrops/main.py \
  backend/tests/unit/api/v1/test_contexthub.py
git commit -m "feat(contexthub): add contexthub API router and app wiring"
```

---

## Task 11: Thread `use_context_hub` through the chat request path

**Files:**
- Modify: `backend/src/agentdrops/api/v1/schema.py`
- Modify: `backend/src/agentdrops/api/v1/chat.py`
- Modify: `backend/src/agentdrops/service/chat_queue_service.py`
- Modify: `backend/src/agentdrops/worker/tasks.py`
- Modify: `backend/tests/unit/service/test_chat_queue_service.py`
- Modify: `backend/tests/unit/api/v1/conftest.py`
- Modify: `backend/tests/unit/api/v1/test_chat.py`
- Modify: `backend/tests/unit/worker/test_tasks.py`

**Interfaces:**
- Produces: `ChatRequest.use_context_hub: bool = False`; `ChatQueueService.enqueue(thread_id, message, *, operation, use_context_hub=False)`; `ChatQueueService.stream(thread_id, message, use_context_hub=False)`; `run_turn_task(thread_id, message, operation, use_context_hub=False)`.

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/service/test_chat_queue_service.py` has its own local `_FakeDelay` (distinct from the one in `tests/unit/api/v1/conftest.py`) whose `.calls` are 3-tuples — update it the same way:

```python
class _FakeDelay:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, bool]] = []

    def __call__(self, thread_id: str, message: str, operation: str, use_context_hub: bool = False) -> None:
        self.calls.append((thread_id, message, operation, use_context_hub))
```

Fix the two existing assertions that will otherwise break:

```python
    assert fake_delay.calls == [("t1", "Research the EV charging market", "chat", False)]
```

(in `test_enqueue_touches_and_resets_status_to_queued_before_dispatching`) and

```python
    assert fake_delay.calls == [("t2", "Focus on the EU", "chat_stream", False)]
```

(in `test_enqueue_dispatches_run_turn_task_with_expected_args`). Then add a new test:

```python
async def test_enqueue_passes_use_context_hub_to_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = _FakeSessionStore()
    fake_delay = _FakeDelay()
    monkeypatch.setattr(chat_queue_service_module.run_turn_task, "delay", fake_delay)
    service = ChatQueueService(sessions, object())  # type: ignore[arg-type]

    await service.enqueue("t1", "msg", operation="chat", use_context_hub=True)

    assert fake_delay.calls == [("t1", "msg", "chat", True)]
```

In `backend/tests/unit/api/v1/conftest.py`, update `_FakeDelay.__call__`'s signature to accept the new 4th argument:

```python
class _FakeDelay:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, bool]] = []

    def __call__(self, thread_id: str, message: str, operation: str, use_context_hub: bool = False) -> None:
        self.calls.append((thread_id, message, operation, use_context_hub))
```

In `backend/tests/unit/api/v1/test_chat.py`, fix the existing assertion that will otherwise break (it currently expects a 3-tuple):

```python
    assert client.fake_delay.calls == [  # type: ignore[attr-defined]
        (thread_id, "Research the EV charging market", "chat", False)
    ]
```

and update the three local `_broken_enqueue` fakes (in `test_chat_stream_emits_error_event_if_enqueue_fails_after_subscribing`, `test_chat_returns_502_even_if_mark_failed_itself_raises`, and `test_chat_stream_still_emits_error_event_even_if_mark_failed_itself_raises`) to accept the new keyword argument `ChatQueueService.enqueue` is now called with, otherwise they raise `TypeError: unexpected keyword argument` instead of the `RuntimeError` these tests are actually exercising:

```python
    async def _broken_enqueue(
        _thread_id: str, _message: str, *, operation: str, use_context_hub: bool = False
    ) -> None:
        raise RuntimeError("enqueue failed")
```

(same signature change in all three places — `_broken_mark_failed` is untouched, it doesn't take `use_context_hub`)

Add a new test in `test_chat.py` asserting `POST /v1/chat` with `{"use_context_hub": true}` reaches the fake delay with that flag set:

```python
def test_chat_forwards_use_context_hub_flag(client: TestClient) -> None:
    response = client.post(
        "/v1/chat", json={"message": "Research EV charging", "use_context_hub": True}
    )
    assert response.status_code == 200
    assert client.fake_delay.calls[-1][3] is True
```

In `backend/tests/unit/worker/test_tasks.py`, add:

```python
def test_run_turn_task_passes_use_context_hub_to_build_market_researcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_build(settings, client, checkpointer, session_factory=None, *, use_context_hub=False):
        captured["use_context_hub"] = use_context_hub
        captured["session_factory"] = session_factory
        return _FakeGraph()

    monkeypatch.setattr(tasks_module, "build_market_researcher", fake_build)

    tasks_module.run_turn_task("t1", "Research the EV charging market", "chat_stream", True)

    assert captured["use_context_hub"] is True
    assert captured["session_factory"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/service/test_chat_queue_service.py tests/unit/api/v1/test_chat.py tests/unit/worker/test_tasks.py -v`
Expected: FAIL — none of the new params exist yet.

- [ ] **Step 3: Add `use_context_hub` to `ChatRequest`**

In `backend/src/agentdrops/api/v1/schema.py`, update `ChatRequest`:

```python
class ChatRequest(BaseModel):
    """One chat turn: an optional existing thread to resume, the user's message, and whether
    this turn may consult Context Hub (uploaded/enterprise knowledge) alongside web search."""

    thread_id: str | None = None
    message: str
    use_context_hub: bool = False
```

- [ ] **Step 4: Thread the flag through `chat.py`**

In `backend/src/agentdrops/api/v1/chat.py`, update both handlers' `queue.enqueue`/`queue.stream` calls:

```python
        await queue.enqueue(
            thread_id, body.message, operation="chat", use_context_hub=body.use_context_hub
        )
```

```python
    async def events() -> AsyncIterator[str]:
        async for event in queue.stream(
            thread_id, body.message, use_context_hub=body.use_context_hub
        ):
            yield _sse(event)
```

- [ ] **Step 5: Thread the flag through `ChatQueueService`**

In `backend/src/agentdrops/service/chat_queue_service.py`, update:

```python
    async def enqueue(
        self, thread_id: str, message: str, *, operation: str, use_context_hub: bool = False
    ) -> None:
        await self._sessions.touch(thread_id, title=message[:CHAT_TITLE_MAX_LENGTH])
        await self._sessions.set_status(thread_id, "queued")
        run_turn_task.delay(thread_id, message, operation, use_context_hub)
```

```python
    async def stream(
        self, thread_id: str, message: str, use_context_hub: bool = False
    ) -> AsyncIterator[dict[str, Any]]:
        try:
            async with open_subscription(self._redis, thread_id) as pubsub:
                await self.enqueue(
                    thread_id, message, operation="chat_stream", use_context_hub=use_context_hub
                )
                async for event in consume_subscription(pubsub):
                    yield event
                    if event.get("type") in _TERMINAL_EVENT_TYPES:
                        return
```

(the `except Exception:` block below is unchanged)

- [ ] **Step 6: Thread the flag through `worker/tasks.py`**

In `backend/src/agentdrops/worker/tasks.py`, update `_execute` and `run_turn_task`:

```python
async def _execute(
    thread_id: str, message: str, operation: str, settings: Settings, use_context_hub: bool
) -> None:
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        engine = create_engine(settings)
        try:
            session_factory = create_session_factory(engine)
            sessions = SessionStore(session_factory)
            audit = AuditLog(session_factory)
            try:
                async with (
                    httpx.AsyncClient(timeout=30.0) as client,
                    checkpointer(settings) as saver,
                ):
                    graph = build_market_researcher(
                        settings, client, saver, session_factory,
                        use_context_hub=use_context_hub,
                    )
                    chat_service = ChatService(graph, sessions, audit)
                    await run_turn(
                        chat_service, thread_id, message, operation=operation, redis=redis
                    )
            except Exception as exc:
                logger.exception("worker setup failed for thread_id=%s", thread_id)
                await sessions.set_status(thread_id, "failed", error=str(exc))
                await audit.record(
                    thread_id, operation=operation, status="failed", detail={"error": str(exc)}
                )
                await publish_event(
                    redis,
                    thread_id,
                    {"type": "error", "thread_id": thread_id, "message": TURN_FAILED_MESSAGE},
                )
        finally:
            await engine.dispose()
    finally:
        await redis.aclose()


@celery_app.task(name="agentdrops.run_turn")  # type: ignore[untyped-decorator]
def run_turn_task(
    thread_id: str, message: str, operation: str, use_context_hub: bool = False
) -> None:
    asyncio.run(_execute(thread_id, message, operation, get_settings(), use_context_hub))
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/service/test_chat_queue_service.py tests/unit/api/v1/test_chat.py tests/unit/worker/test_tasks.py -v`
Expected: PASS

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && pytest -v && ruff check . && mypy src`
Expected: PASS — this touches several existing call sites (`_FakeGraph`/`build_market_researcher` fakes across test files), so re-run everything, not just the files above.

- [ ] **Step 9: Commit**

```bash
git add backend/src/agentdrops/api/v1/schema.py backend/src/agentdrops/api/v1/chat.py \
  backend/src/agentdrops/service/chat_queue_service.py backend/src/agentdrops/worker/tasks.py \
  backend/tests/unit/service/test_chat_queue_service.py backend/tests/unit/api/v1/conftest.py \
  backend/tests/unit/api/v1/test_chat.py backend/tests/unit/worker/test_tasks.py
git commit -m "feat(contexthub): thread use_context_hub through the chat request path"
```

---

## Task 12: Frontend — types and API client functions

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Produces: `ContextHubDocument` type; `listContextHubDocuments()`, `uploadContextHubFile(file: File)`, `addContextHubUrl(url: string)`, `deleteContextHubDocument(id: string)` — Task 13's panel component depends on these exact names/signatures.

Frontend has no test runner configured beyond `npm run lint`/`npm run build` per `frontend/AGENTS.md` conventions observed in this repo (no `*.test.tsx` files exist) — this task's "test" is a manual exercise via the dev server plus `npm run build`/`npm run lint` passing.

- [ ] **Step 1: Add the `ContextHubDocument` type**

In `frontend/src/lib/types.ts`, add:

```typescript
export type ContextHubDocumentStatus = "processing" | "ready" | "failed";

export type ContextHubDocument = {
  id: string;
  title: string;
  source_type: "file" | "url";
  status: ContextHubDocumentStatus;
  error: string | null;
  created_at: string;
};
```

- [ ] **Step 2: Add API client functions**

In `frontend/src/lib/api.ts`, add `ContextHubDocument` to the import from `@/lib/types`, then add at the end of the file:

```typescript
/** List every Context Hub document (global — not scoped to a session), newest first. */
export async function listContextHubDocuments(): Promise<ContextHubDocument[]> {
  const response = await fetch(`${API_BASE_URL}/v1/contexthub/documents`);
  const { documents } = await unwrap<{ documents: ContextHubDocument[] }>(response);
  return documents;
}

/** Upload a file into Context Hub. Ingestion (extract/chunk/embed) runs async — the returned
 * record starts at status "processing"; re-fetch the list to see it flip to "ready"/"failed". */
export async function uploadContextHubFile(file: File): Promise<ContextHubDocument> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${API_BASE_URL}/v1/contexthub/documents`, {
    method: "POST",
    body: formData,
  });
  return unwrap<ContextHubDocument>(response);
}

/** Add a URL into Context Hub; fetched and ingested the same way as an uploaded file. */
export async function addContextHubUrl(url: string): Promise<ContextHubDocument> {
  const response = await fetch(`${API_BASE_URL}/v1/contexthub/urls`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  return unwrap<ContextHubDocument>(response);
}

/** Permanently delete a Context Hub document. */
export async function deleteContextHubDocument(id: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/v1/contexthub/documents/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`Failed to delete Context Hub document ${id} (status ${response.status})`);
  }
}
```

- [ ] **Step 3: Verify the build**

Run: `cd frontend && npm run lint && npm run build`
Expected: PASS (no components use these functions yet, but they must type-check cleanly against `types.ts`).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts
git commit -m "feat(contexthub): add frontend types and API client functions"
```

---

## Task 13: Frontend — Context Hub sidebar panel

**Files:**
- Create: `frontend/src/components/app/contexthub-panel.tsx`
- Modify: `frontend/src/components/app/sidebar.tsx`

**Interfaces:**
- Consumes: `listContextHubDocuments`, `uploadContextHubFile`, `addContextHubUrl`, `deleteContextHubDocument` (Task 12).
- Produces: `<ContextHubPanel open, onClose />` component; a new button in `Sidebar`'s footer that opens it.

- [ ] **Step 1: Build the panel component**

Create `frontend/src/components/app/contexthub-panel.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { FileText, Link2, Loader2, Trash2, Upload, X } from "lucide-react";
import {
  addContextHubUrl,
  deleteContextHubDocument,
  listContextHubDocuments,
  uploadContextHubFile,
} from "@/lib/api";
import { ContextHubDocument } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<ContextHubDocument["status"], string> = {
  processing: "Processing...",
  ready: "Ready",
  failed: "Failed",
};

export function ContextHubPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [documents, setDocuments] = useState<ContextHubDocument[]>([]);
  const [urlInput, setUrlInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    listContextHubDocuments()
      .then(setDocuments)
      .catch(() => setError("Couldn't load Context Hub documents."));
  };

  useEffect(() => {
    if (open) refresh();
  }, [open]);

  const handleFileUpload = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      await uploadContextHubFile(file);
      refresh();
    } catch {
      setError(`Couldn't upload ${file.name}.`);
    } finally {
      setBusy(false);
    }
  };

  const handleAddUrl = async () => {
    const url = urlInput.trim();
    if (!url) return;
    setBusy(true);
    setError(null);
    try {
      await addContextHubUrl(url);
      setUrlInput("");
      refresh();
    } catch {
      setError("Couldn't add that URL.");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (id: string) => {
    setDocuments((prev) => prev.filter((d) => d.id !== id));
    try {
      await deleteContextHubDocument(id);
    } catch {
      refresh(); // roll back the optimistic removal if the delete failed
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-lg border bg-background shadow-lg">
        <div className="flex items-center justify-between border-b px-5 py-4">
          <h2 className="text-sm font-semibold">Context Hub</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 border-b px-5 py-4">
          <label
            className={cn(
              "flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed py-3 text-sm text-muted-foreground hover:bg-accent",
              busy && "pointer-events-none opacity-60"
            )}
          >
            <Upload className="h-4 w-4" />
            Upload PDF, DOCX, TXT, or CSV
            <input
              type="file"
              accept=".pdf,.docx,.txt,.csv"
              className="hidden"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFileUpload(file);
                e.target.value = "";
              }}
            />
          </label>

          <div className="flex items-center gap-2">
            <input
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddUrl()}
              placeholder="https://internal.example.com/wiki/..."
              disabled={busy}
              className="flex-1 rounded-md border bg-background/40 px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus:border-ring"
            />
            <button
              onClick={handleAddUrl}
              disabled={busy || !urlInput.trim()}
              className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
            >
              <Link2 className="h-3.5 w-3.5" />
              Add
            </button>
          </div>
          {error && <div className="text-xs text-destructive">{error}</div>}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-3">
          {documents.length === 0 ? (
            <div className="py-6 text-center text-xs text-muted-foreground">
              Nothing uploaded yet.
            </div>
          ) : (
            <ul className="space-y-1">
              {documents.map((doc) => (
                <li
                  key={doc.id}
                  className="flex items-center gap-2 rounded-md px-2 py-2 hover:bg-accent"
                >
                  {doc.source_type === "file" ? (
                    <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <Link2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm">{doc.title}</div>
                    <div
                      className={cn(
                        "text-xs",
                        doc.status === "failed" ? "text-destructive" : "text-muted-foreground"
                      )}
                    >
                      {doc.status === "processing" && (
                        <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />
                      )}
                      {STATUS_LABEL[doc.status]}
                      {doc.status === "failed" && doc.error ? `: ${doc.error}` : ""}
                    </div>
                  </div>
                  <button
                    title="Delete"
                    onClick={() => handleDelete(doc.id)}
                    className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add the sidebar button**

In `frontend/src/components/app/sidebar.tsx`:

Add to the imports:

```typescript
import { ContextHubPanel } from "@/components/app/contexthub-panel";
```

and add `Database` to the existing `lucide-react` import list.

Add state near the other `useState` calls in `Sidebar`:

```typescript
  const [contextHubOpen, setContextHubOpen] = useState(false);
```

Add a button in the footer `<div className="space-y-2 border-t px-4 py-4">` block, above the theme toggle button:

```tsx
        <button
          onClick={() => setContextHubOpen(true)}
          className="flex w-full items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-accent"
        >
          <Database className="h-4 w-4" />
          Context Hub
        </button>
```

And render the panel just before the closing `</aside>` tag:

```tsx
      <ContextHubPanel open={contextHubOpen} onClose={() => setContextHubOpen(false)} />
```

- [ ] **Step 3: Manually verify in the browser**

Run: `cd backend && make run` (or `uvicorn agentdrops.main:app --reload --port 8000` + `celery -A agentdrops.worker.celery_app worker` in a second terminal — check `backend/README.md`/`Makefile` for the exact commands) and `cd frontend && npm run dev`.

Open `http://localhost:3000`, click "Context Hub" in the sidebar footer, upload a small `.txt` file, confirm it appears with status "Processing..." and (after the worker finishes) "Ready". Add a URL and confirm the same. Delete one and confirm it disappears.

- [ ] **Step 4: Verify the build**

Run: `cd frontend && npm run lint && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/app/contexthub-panel.tsx frontend/src/components/app/sidebar.tsx
git commit -m "feat(contexthub): add Context Hub sidebar panel"
```

---

## Task 14: Frontend — chat toggle wiring

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/components/app/chat-panel.tsx`

**Interfaces:**
- Consumes: `ContextHubDocument` list (Task 12/13, to know if there's anything to toggle on).
- Produces: `streamChat(message, threadId, useContextHub, onEvent)` (adds a parameter); a toggle control in `ChatPanel`'s input area, state owned by `page.tsx`.

- [ ] **Step 1: Extend `streamChat` to send the flag**

In `frontend/src/lib/api.ts`, update `streamChat`'s signature and body:

```typescript
export async function streamChat(
  message: string,
  threadId: string | null,
  useContextHub: boolean,
  onEvent: (event: StreamEvent) => void
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      thread_id: threadId,
      message,
      use_context_hub: useContextHub,
    }),
  });
  // ... rest of the function body is unchanged
```

- [ ] **Step 2: Add toggle state in `page.tsx`**

In `frontend/src/app/page.tsx`, add state near the other `useState` calls:

```typescript
  const [useContextHub, setUseContextHub] = useState(false);
```

Update the `sendMessage` function's `streamChat` call:

```typescript
        await streamChat(text, threadId, useContextHub, (event) => {
```

Pass the new prop/setter down to `ChatPanel`:

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
          onOpenDrawer={(mode) => {
            setDrawerMode(mode ?? "progress");
            setDrawerOpen(true);
          }}
          clarifySuggestions={clarifySuggestions}
          setClarifySuggestions={setClarifySuggestions}
          starterSuggestions={starterSuggestions}
          useContextHub={useContextHub}
          setUseContextHub={setUseContextHub}
        />
```

- [ ] **Step 3: Add the toggle control in `ChatPanel`**

In `frontend/src/components/app/chat-panel.tsx`, add `Database` to the `lucide-react` import, add the two new props to the destructured props and its type annotation:

```typescript
  useContextHub,
  setUseContextHub,
}: {
  // ...existing prop types...
  useContextHub: boolean;
  setUseContextHub: (v: boolean) => void;
}) {
```

In the input area's badge row (next to the existing "Deep Research" badge), add a toggle button:

```tsx
            <span className="flex items-center gap-1.5 rounded-full bg-blue-500/10 px-2.5 py-1 text-xs font-medium text-blue-500">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
              Deep Research
            </span>
            <button
              type="button"
              onClick={() => setUseContextHub(!useContextHub)}
              title="Include your uploaded Context Hub knowledge in this research"
              className={cn(
                "ml-2 flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors",
                useContextHub
                  ? "border-blue-500 bg-blue-500/10 text-blue-500"
                  : "text-muted-foreground hover:bg-accent"
              )}
            >
              <Database className="h-3 w-3" />
              Use uploaded knowledge
            </button>
```

(placed inside the same flex row as the existing badge/submit button — check the surrounding `<div className="mt-2 flex items-center justify-between">` block and add it there, before the submit button.)

- [ ] **Step 4: Manually verify in the browser**

With the backend + worker running (Task 13's setup), upload a `.txt` file with a distinctive fact via Context Hub, wait for it to reach "Ready", toggle "Use uploaded knowledge" on, and ask a question whose answer depends on that fact. Confirm the toggle's on/off state visibly changes and a network inspector shows `use_context_hub` in the `/v1/chat/stream` request body.

- [ ] **Step 5: Verify the build**

Run: `cd frontend && npm run lint && npm run build`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/app/page.tsx frontend/src/components/app/chat-panel.tsx
git commit -m "feat(contexthub): add chat toggle for using uploaded knowledge"
```
