import uuid

from fastapi.testclient import TestClient


async def _run_turn(
    client: TestClient, thread_id: str, message: str, *, operation: str = "chat"
) -> None:
    """Directly drive `ChatService.run_turn` to simulate what the background worker does —
    `/chat`/`/chat/stream` now only enqueue a Celery task rather than executing the graph
    inline, so these status/report-reading tests populate state the same way the worker would."""
    service = client.app.state.chat_service
    async for _ in service.run_turn(thread_id, message, operation=operation):
        pass


def test_get_research_status_unknown_thread_returns_404(client: TestClient) -> None:
    response = client.get("/v1/research/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body == {
        "success": False,
        "data": {"code": 404, "description": "Not found", "message": "Unknown thread_id"},
    }


async def test_get_research_status_reflects_clarifying_then_done(client: TestClient) -> None:
    thread_id = str(uuid.uuid4())
    await _run_turn(client, thread_id, "Research the EV charging market")

    clarifying = client.get(f"/v1/research/{thread_id}")
    assert clarifying.json()["data"]["status"] == "clarifying"
    assert clarifying.json()["data"]["report"] is None

    await _run_turn(client, thread_id, "Focus on the EU")
    done = client.get(f"/v1/research/{thread_id}")
    assert done.json()["data"]["status"] == "done"
    assert done.json()["data"]["report"] == "# EV Charging Market Report"


async def test_get_research_report_before_done_returns_404(client: TestClient) -> None:
    thread_id = str(uuid.uuid4())
    await _run_turn(client, thread_id, "Research the EV charging market", operation="chat_stream")

    response = client.get(f"/v1/research/{thread_id}/report")

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["data"]["message"] == "Report not available for this thread_id"


async def test_get_research_report_after_done_returns_report_and_sources(
    client: TestClient,
) -> None:
    thread_id = str(uuid.uuid4())
    await _run_turn(client, thread_id, "Research the EV charging market", operation="chat_stream")
    await _run_turn(client, thread_id, "Focus on the EU", operation="chat_stream")

    response = client.get(f"/v1/research/{thread_id}/report")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["report"] == "# EV Charging Market Report"
    assert data["sources"] == [{"topic": "EU", "summary": "EU findings"}]
