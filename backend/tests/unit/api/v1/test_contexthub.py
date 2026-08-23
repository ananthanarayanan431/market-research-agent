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
    service.max_upload_mb = 50  # matches Settings.contexthub_max_upload_mb's default
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


def test_upload_document_rejects_files_over_the_configured_size_cap(
    client: TestClient, contexthub_service: AsyncMock
) -> None:
    contexthub_service.max_upload_mb = 1
    oversized = b"x" * (2 * 1024 * 1024)

    response = client.post(
        "/v1/contexthub/documents",
        files={"file": ("report.pdf", oversized, "application/pdf")},
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
