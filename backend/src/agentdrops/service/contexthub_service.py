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
    def __init__(
        self, store: ContextHubStore, storage: ContextHubStorage, max_upload_mb: int
    ) -> None:
        self._store = store
        self._storage = storage
        self.max_upload_mb = max_upload_mb
        """Public — the router (Task 10) reads this to reject oversized uploads before ever
        calling `upload_file`, the same way it reads `_resolve_content_type` for extensions."""

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
