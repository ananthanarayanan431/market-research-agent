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
