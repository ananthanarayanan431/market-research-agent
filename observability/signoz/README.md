# SigNoz assets

Version-controlled SigNoz dashboard and alert definitions for the market-research agent.
They read the telemetry the app emits (see `backend/src/agentdrops/observability/`), so they
work against any SigNoz instance the app is pointed at.

SigNoz itself is deployed from `casting.yaml` at the repo root (`foundryctl cast`).

## Dashboard — `dashboards/agentdrops-agent.json`

Six panels:

| Panel | Source | Query |
|-------|--------|-------|
| Tool call throughput by tool | metric | `rate(agentdrops.tool_call.duration.count)` by `tool_name` |
| Tool call P95 latency by tool | metric | `p95` of `agentdrops.tool_call.duration.bucket` by `tool_name` |
| Tool call failures by tool | metric | `rate(...count)` filtered `success=false` by `tool_name` |
| Research turn P95 duration | trace | `p95(duration_nano)` where `name=research.turn` |
| Research turns by outcome | trace | `count()` where `name=research.turn` by `research.outcome` |
| Avg tokens per research turn | trace | `avg(gen_ai.usage.total_tokens)` where `name=research.turn` |

Import: **Dashboards → + New → Import JSON**, paste the file. Or POST to
`/api/v1/dashboards` with an authed bearer token.

## Alerts — `alerts/*.json`

- **tool-call-failure-rate** — failed tool-call rate (`success=false`) above `0.2/s` over 5m.
- **slow-research-turns** — P95 `research.turn` duration above `120s` over 5m.

Both reference a notification channel named `agentdrops-webhook`. Create a channel with that
name (Settings → Notification Channels) — the committed one is a **placeholder webhook**; point
it at your real Slack / email / webhook. Then POST each file to `/api/v2/rules`, or recreate the
rule in the UI using the query in the file.

## Metric / span names these depend on

Changing any of these in the backend means updating the panels/alerts here too:

- Metric `agentdrops.tool_call.duration` (histogram) with labels `tool_name`, `success` —
  emitted by `record_tool_call` from the search pipeline.
- Span `research.turn` with attributes `research.outcome`, `gen_ai.usage.total_tokens` —
  emitted per turn in `api/main.py`.
