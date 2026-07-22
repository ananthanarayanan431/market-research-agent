from fastapi.testclient import TestClient

from tests.unit.api.v1.conftest import parse_sse


def test_get_research_status_unknown_thread_returns_404(client: TestClient) -> None:
    response = client.get("/v1/research/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body == {
        "success": False,
        "data": {"code": 404, "description": "Not found", "message": "Unknown thread_id"},
    }


def test_get_research_status_reflects_clarifying_then_done(client: TestClient) -> None:
    first = client.post("/v1/chat", json={"message": "Research the EV charging market"})
    thread_id = first.json()["data"]["thread_id"]

    clarifying = client.get(f"/v1/research/{thread_id}")
    assert clarifying.json()["data"]["status"] == "clarifying"
    assert clarifying.json()["data"]["report"] is None

    client.post("/v1/chat", json={"thread_id": thread_id, "message": "Focus on the EU"})
    done = client.get(f"/v1/research/{thread_id}")
    assert done.json()["data"]["status"] == "done"
    assert done.json()["data"]["report"] == "# EV Charging Market Report"


def test_get_research_report_before_done_returns_404(client: TestClient) -> None:
    first = client.post(
        "/v1/chat/stream", json={"message": "Research the EV charging market"}
    )
    thread_id = parse_sse(first.text)[0]["thread_id"]

    response = client.get(f"/v1/research/{thread_id}/report")

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["data"]["message"] == "Report not available for this thread_id"


def test_get_research_report_after_done_returns_report_and_sources(client: TestClient) -> None:
    first = client.post(
        "/v1/chat/stream", json={"message": "Research the EV charging market"}
    )
    thread_id = parse_sse(first.text)[0]["thread_id"]
    client.post("/v1/chat/stream", json={"thread_id": thread_id, "message": "Focus on the EU"})

    response = client.get(f"/v1/research/{thread_id}/report")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["report"] == "# EV Charging Market Report"
    assert data["sources"] == [{"topic": "EU", "summary": "EU findings"}]
