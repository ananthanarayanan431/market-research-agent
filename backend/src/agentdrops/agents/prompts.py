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

REPORT_PLAN_PROMPT = """You are planning the structure of a long, in-depth market-research report.
Today is {date}.

Research brief:
{research_brief}

Findings from research sub-agents:
{findings}

Break the report into an ordered list of sections that together cover the brief end-to-end, with
no gaps and no overlap between sections. For each section, give:
- a short title
- a description of exactly what it must cover: the sub-questions it answers and which findings
  it should draw on
- a target word count between {min_words} and {max_words}

Plan for a genuinely long, thorough report — use {min_sections} to {max_sections} sections to
cover the brief in depth, not a short summary. Open with an executive-summary section and close
with a conclusion/outlook section."""

REPORT_SECTION_PROMPT = """You are drafting one section of a long market-research report. Today
is {date}.

Research brief:
{research_brief}

Findings from research sub-agents:
{findings}

Full report plan, for context only (write just your assigned section, not the others):
{plan}

Report written so far:
{written_so_far}

Write the section titled "{section_title}". It must cover:
{section_description}

Target length: about {target_words} words. Requirements:
- Output only this section's prose — no heading, one will be added automatically.
- Do not repeat or re-summarize content already written above; continue the report naturally.
- Back factual claims with inline citations to source URLs from the findings.
- Do not invent facts beyond what the findings support.
- {is_final_hint}"""
