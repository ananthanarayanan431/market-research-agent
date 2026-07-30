"""Static, non-env constants shared across the API layer.

Unlike `Settings`, these aren't meant to be overridden per-deployment — they're presentation-layer
constants that happen to be shared by more than one call site, so they live here instead of being
duplicated or buried in a route module.
"""

CHAT_TITLE_MAX_LENGTH = 80
"""A session's title is the opening message, trimmed to this length for the sidebar."""

CHAT_NODE_LABELS: dict[str, str] = {
    "clarify_with_user": "Reviewing your request",
    "write_research_brief": "Planning research approach",
    "supervisor": "Coordinating research",
    "final_report_generation": "Synthesizing findings",
}
"""Top-level graph nodes that should surface as a progress step in the `/chat/stream` SSE feed."""
