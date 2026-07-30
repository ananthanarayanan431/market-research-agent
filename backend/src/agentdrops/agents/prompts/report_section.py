"""System prompt for the writer's per-section drafting call."""

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

<Task>
Write the section titled "{section_title}". It must cover:
{section_description}
</Task>

Target length: about {target_words} words.

<Requirements>
- Output only this section's prose — no heading, one will be added automatically.
- Do not repeat or re-summarize content already written above; continue the report naturally.
- Back factual claims with inline citations to source URLs from the findings, using
  [Title](URL) markdown link format.
- Do not invent facts beyond what the findings support — if the findings don't cover something,
  don't assert it.
- Use clear, plain language and proper structure (bullet points where they aid clarity,
  paragraphs otherwise). Do not refer to yourself as the writer or describe what you're doing —
  write the report content only, no self-referential commentary.
- {is_final_hint}
</Requirements>"""
