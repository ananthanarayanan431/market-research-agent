from typing import Any

from agentdrops.webtools.base import BaseSearchTool, SearchResult, SearchToolError

__all__ = ["BaseSearchTool", "SearchResult", "SearchToolError", "build_search_tools"]


def __getattr__(name: str) -> Any:
    if name == "build_search_tools":
        from agentdrops.webtools.registry import build_search_tools
        return build_search_tools
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
