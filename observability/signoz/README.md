# SigNoz assets

Version-controlled SigNoz dashboard and alert definitions for the market-research agent.
They read the telemetry the app emits (see `backend/src/agentdrops/observability/`), so they
work against any SigNoz instance the app is pointed at.

## Running SigNoz

Two equivalent ways to bring the stack up:

```bash
# 1. Foundry (source of truth — regenerates everything from casting.yaml at the repo root)
foundryctl cast -f casting.yaml

# 2. Plain docker compose (committed snapshot of the Foundry-generated stack, no foundryctl needed)
docker compose -f observability/signoz/stack/compose.yaml up -d
```

`stack/` is a committed copy of what `foundryctl cast` generates (8 services: SigNoz UI,
OTLP ingester, ClickHouse + keeper, metastore, and the MCP server). It exposes **8080** (UI),
**4317/4318** (OTLP gRPC/HTTP), and **8000** (MCP). `casting.yaml` + `casting.yaml.lock` remain
the source of truth — regenerate the snapshot with `foundryctl forge` if you change them.

First run only: open http://localhost:8080 and create the admin account, or the collector's OTLP
receivers stay down until setup completes.

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
