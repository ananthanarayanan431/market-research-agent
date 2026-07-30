"""System prompt for summarizing one search result's page content."""

SUMMARIZE_PROMPT = """Summarize the following page content for a market-research report. This
summary will be used by a downstream research agent, so preserve the details that matter more
than you shorten the text.

<Webpage Content>
{content}
</Webpage Content>

<Guidelines>
- Identify the main topic or purpose of the page.
- Keep concrete facts, figures, dates, and data points central to its content.
- Keep any quotes worth citing directly, verbatim.
- Preserve chronological order if the content is time-sensitive.
- Preserve lists or step-by-step details if present.
- For news content, cover the who/what/when/where/why/how. For data or research content,
  preserve methodology and results. For product pages, keep key features and specifications.
</Guidelines>

Aim for roughly 25-30% of the original length unless the content is already concise — the goal
is a summary that stands alone as a usable source, not a one-line gist."""
