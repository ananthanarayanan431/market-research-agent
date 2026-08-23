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
