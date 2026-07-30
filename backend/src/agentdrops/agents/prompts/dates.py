"""Shared date helper for prompt templates."""

from datetime import UTC, datetime


def get_today_str() -> str:
    """Today's date formatted for prompts (uses %d, not %-d, so it also works on Windows)."""
    return datetime.now(UTC).strftime("%B %d, %Y")
