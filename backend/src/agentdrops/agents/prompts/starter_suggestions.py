"""System prompt for generating idle-chat starter prompt suggestions."""

STARTER_SUGGESTIONS_PROMPT = """You are generating example prompts for a finance research
agent's idle chat screen. Today is {date}.

<Task>
Propose 3 short, varied example research requests a user might submit.
</Task>

<Guidelines>
- Keep every example within finance, but vary the sub-domain each time so the three don't read
  as a set — for example one equity/earnings question, one macro or rates question, and one
  corporate-finance or personal-finance question.
- Each one should be a single sentence, phrased the way a user would actually type it into a
  chat box (not a formal research brief).
- Keep them concrete: name an actual company, ticker, sector, or macro event rather than a
  vague topic.
</Guidelines>"""
