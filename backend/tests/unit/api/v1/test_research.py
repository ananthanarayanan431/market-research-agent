import uuid

from fastapi.testclient import TestClient

from tests.unit.api.v1.conftest import run_turn as _run_turn


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
