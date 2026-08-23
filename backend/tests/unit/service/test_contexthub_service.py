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
    service = ContextHubService(store, storage, max_upload_mb=50)

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
    service = ContextHubService(store, storage, max_upload_mb=50)

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
    service = ContextHubService(store, storage, max_upload_mb=50)

    result = await service.delete_document("doc-1")

    storage.delete.assert_awaited_once_with("doc-1/report.pdf")
    store.delete_document.assert_awaited_once_with("doc-1")
    assert result == "deleted"


async def test_delete_document_not_found() -> None:
    store = AsyncMock()
    store.get_document.return_value = None
    storage = AsyncMock()
    service = ContextHubService(store, storage, max_upload_mb=50)

    assert await service.delete_document("missing") == "not_found"
    storage.delete.assert_not_awaited()
