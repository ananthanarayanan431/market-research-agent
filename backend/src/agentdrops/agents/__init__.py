"""Market-research agent: clarify -> brief -> supervisor -> research -> writer, on LangGraph."""

from typing import Any

__all__ = ["build_market_researcher"]


def __getattr__(name: str) -> Any:
    if name == "build_market_researcher":
        from agentdrops.agents.graph import build_market_researcher

        return build_market_researcher
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
