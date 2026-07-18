"""Structured-output contracts the LLM is forced to emit at specific pipeline stages."""

from pydantic import BaseModel, Field


class ClarifyWithUser(BaseModel):
    """Whether the chat history has enough detail to research, or needs a clarifying question."""

    need_clarification: bool = Field(
        description="True if the request is too ambiguous to research as-is."
    )
    question: str = Field(description="Clarifying question to ask the user, if needed.")
    verification: str = Field(
        description="Short message confirming scope, used when no clarification is needed."
    )


class ResearchQuestion(BaseModel):
    """A single, self-contained research brief distilled from the chat history."""

    research_brief: str = Field(
        description="The research question to hand to the supervisor, in one paragraph."
    )


class Summary(BaseModel):
    """Condensed summary of one search result's page content."""

    summary: str = Field(description="Concise summary of the page content.")
    key_excerpts: str = Field(description="Verbatim quotes worth citing directly, if any.")
