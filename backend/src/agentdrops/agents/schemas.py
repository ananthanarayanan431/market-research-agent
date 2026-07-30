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
    suggestions: list[str] = Field(
        default_factory=list,
        description="2-5 short, concrete example answers to `question`, specific to what it "
        "actually asks (e.g. example regions/timeframes for a scoping question, example "
        "competitor names for a comparison question). Empty when need_clarification is false.",
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


class ReportSection(BaseModel):
    """One planned section of the final report, drafted independently in the writer node."""

    title: str = Field(description="Short section heading.")
    description: str = Field(
        description="What this section must cover: the sub-questions it answers and which "
        "findings it should draw on. Written for the model drafting it, not the end reader."
    )
    target_words: int = Field(description="Target word count for this section's prose.")


class ReportPlan(BaseModel):
    """Ordered breakdown of the report into sections, produced before any prose is written."""

    sections: list[ReportSection] = Field(
        description="Ordered sections that together cover the research brief end-to-end, "
        "with no gaps and no overlap."
    )


class StarterSuggestions(BaseModel):
    """Example research prompts shown on the idle chat state, before the user has typed anything."""

    prompts: list[str] = Field(
        description="3 short, varied example market-research prompts a user might submit — "
        "different industries/markets each time, one sentence each."
    )
