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
