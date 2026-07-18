"""FastAPI app exposing the market-research agent over a single /chat endpoint."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from langchain_core.messages import HumanMessage

from agentdrops.agents.graph import build_market_researcher
from agentdrops.api.schema import ChatRequest, ChatResponse
from agentdrops.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the shared httpx client and compiled agent graph once per process lifetime."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        app.state.graph = build_market_researcher(settings, client)
        yield


app = FastAPI(title="Agentdrops Market Research Agent", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Advance one chat turn: clarify, research, and report, resuming state via `thread_id`."""
    thread_id = request.thread_id or str(uuid.uuid4())
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

    graph = app.state.graph
    inputs = {"messages": [HumanMessage(content=request.message)]}
    result = await graph.ainvoke(inputs, config=config)

    final_report = result.get("final_report")
    if final_report:
        return ChatResponse(
            thread_id=str(uuid.uuid4()),
            response=final_report,
            is_followup=False,
            report=final_report,
        )

    last_message = result["messages"][-1]
    return ChatResponse(thread_id=thread_id, response=str(last_message.content), is_followup=True)
