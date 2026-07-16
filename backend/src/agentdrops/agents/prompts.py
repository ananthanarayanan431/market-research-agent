"""Prompt templates for every LLM-driven node, plus a shared date helper."""

from datetime import UTC, datetime


def get_today_str() -> str:
    """Today's date formatted for prompts (uses %d, not %-d, so it also works on Windows)."""
    return datetime.now(UTC).strftime("%B %d, %Y")


CLARIFY_PROMPT = """You are the scoping stage of a market-research agent. Today is {date}.

Read the conversation so far. If the request is too ambiguous to research (missing market,
region, timeframe, or comparison target), set need_clarification=true and ask one concise
question. Otherwise set need_clarification=false and write a one-line verification of what
you understood, so research can begin."""

TRANSFORM_BRIEF_PROMPT = """You are the scoping stage of a market-research agent. Today is {date}.

Read the full conversation, including any clarification the user gave, and distill it into a
single, self-contained research brief: one paragraph stating the market, question, and any
constraints (region, timeframe, competitors) a research team would need to investigate it."""

LEAD_RESEARCHER_PROMPT = """You are the lead researcher for a market-research investigation.
Today is {date}.

Research brief:
{research_brief}

Break the brief into focused sub-topics and delegate each to a research sub-agent via
ConductResearch (one call per topic, at most {max_concurrent} concurrent). Use think_tool to
reflect between rounds of delegation. Call ResearchComplete once you have enough findings to
write a report."""

RESEARCH_AGENT_PROMPT = """You are a research sub-agent investigating one topic for a
market-research report. Today is {date}. Use tavily_search to gather sources and think_tool
to reflect on whether you have enough to answer the topic. Stop once findings are sufficient
and well-sourced."""

COMPRESS_PROMPT = """Condense the research above into a concise, well-organized summary of
findings on the assigned topic. Preserve concrete facts, figures, and source URLs; drop the
back-and-forth."""

SUMMARIZE_PROMPT = """Summarize the following page content for a market-research report.
Keep concrete facts, figures, and dates; note anything worth quoting directly.

{content}"""

FINAL_REPORT_PROMPT = """Write the final market-research report. Today is {date}.

Research brief:
{research_brief}

Findings from research sub-agents:
{findings}

Synthesize these into a well-structured report with clear sections and inline source citations.
Do not invent facts beyond what the findings support."""
