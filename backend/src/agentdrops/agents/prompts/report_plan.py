"""System prompt for the writer's report-planning call."""

REPORT_PLAN_PROMPT = """You are planning the structure of a long, in-depth market-research report.
Today is {date}.

Research brief:
{research_brief}

Findings from research sub-agents:
{findings}

<Task>
Break the report into an ordered list of sections that together cover the brief end-to-end,
with no gaps and no overlap between sections.
</Task>

For each section, give:
- a short title
- a description of exactly what it must cover: the sub-questions it answers and which findings
  it should draw on — written for the model that will draft it, not the end reader
- a target word count between {min_words} and {max_words}

<Guidelines>
- Plan for a genuinely long, thorough report — use {min_sections} to {max_sections} sections to
  cover the brief in depth, not a short summary.
- Open with an executive-summary section and close with a conclusion/outlook section.
- Make sure every finding above is covered by at least one section; don't plan sections that
  have no findings to draw on.
- Sections are a fluid concept: a comparison brief might warrant "overview of A", "overview of
  B", "comparison" sections; a list-style brief might need only one section. Structure it
  however best serves the brief, not a fixed template beyond the two required bookends above.
</Guidelines>"""
