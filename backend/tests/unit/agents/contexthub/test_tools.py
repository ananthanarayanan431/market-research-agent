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
