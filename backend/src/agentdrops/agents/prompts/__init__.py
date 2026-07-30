"""Prompt templates for every LLM-driven node, plus a shared date helper.

Each prompt lives in its own module under this package; this file re-exports them so existing
`from agentdrops.agents.prompts import X` imports keep working unchanged.
"""

from agentdrops.agents.prompts.clarify import CLARIFY_PROMPT
from agentdrops.agents.prompts.compress_research import COMPRESS_PROMPT
from agentdrops.agents.prompts.dates import get_today_str
from agentdrops.agents.prompts.lead_researcher import LEAD_RESEARCHER_PROMPT
from agentdrops.agents.prompts.report_plan import REPORT_PLAN_PROMPT
from agentdrops.agents.prompts.report_section import REPORT_SECTION_PROMPT
from agentdrops.agents.prompts.research_agent import RESEARCH_AGENT_PROMPT
from agentdrops.agents.prompts.starter_suggestions import STARTER_SUGGESTIONS_PROMPT
from agentdrops.agents.prompts.summarize_webpage import SUMMARIZE_PROMPT
from agentdrops.agents.prompts.transform_brief import TRANSFORM_BRIEF_PROMPT

__all__ = [
    "CLARIFY_PROMPT",
    "COMPRESS_PROMPT",
    "LEAD_RESEARCHER_PROMPT",
    "REPORT_PLAN_PROMPT",
    "REPORT_SECTION_PROMPT",
    "RESEARCH_AGENT_PROMPT",
    "STARTER_SUGGESTIONS_PROMPT",
    "SUMMARIZE_PROMPT",
    "TRANSFORM_BRIEF_PROMPT",
    "get_today_str",
]
