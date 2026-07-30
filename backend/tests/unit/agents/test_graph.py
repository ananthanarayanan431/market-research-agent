import httpx
from langgraph.checkpoint.memory import InMemorySaver

from agentdrops.agents.graph import build_market_researcher
from tests.unit.agents.conftest import make_settings


async def test_build_market_researcher_compiles_with_the_given_checkpointer() -> None:
    checkpointer = InMemorySaver()
    async with httpx.AsyncClient() as client:
        graph = build_market_researcher(make_settings(), client, checkpointer)

    assert graph.checkpointer is checkpointer
