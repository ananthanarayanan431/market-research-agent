from fastapi.testclient import TestClient

from tests.unit.api.v1.conftest import parse_sse


def test_chat_first_turn_asks_for_clarification(client: TestClient) -> None:
    response = client.post("/v1/chat", json={"message": "Research the EV charging market"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["is_followup"] is True
    assert data["response"] == "Which region should I focus on?"
    assert data["report"] is None

    audit = client.app.state.audit.records
    assert len(audit) == 1
    assert audit[0]["thread_id"] == data["thread_id"]
    assert audit[0]["operation"] == "chat"
    assert audit[0]["status"] == "clarify"
    assert audit[0]["detail"] == {}


def test_chat_follow_up_returns_final_report(client: TestClient) -> None:
    first = client.post("/v1/chat", json={"message": "Research the EV charging market"})
    thread_id = first.json()["data"]["thread_id"]

    second = client.post("/v1/chat", json={"thread_id": thread_id, "message": "Focus on the EU"})

    data = second.json()["data"]
    assert data["is_followup"] is False
    assert data["report"] == "# EV Charging Market Report"
    assert data["thread_id"] == thread_id

    audit = client.app.state.audit.records
    assert len(audit) == 2
    assert audit[1]["thread_id"] == thread_id
    assert audit[1]["operation"] == "chat"
    assert audit[1]["status"] == "done"
    assert audit[1]["detail"] == {"report_chars": len(data["report"])}


def test_chat_stream_first_turn_emits_clarify_event(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/stream", json={"message": "Research the EV charging market"}
    )

    assert response.status_code == 200
    events = parse_sse(response.text)
    assert events == [
        {
            "type": "clarify",
            "thread_id": events[0]["thread_id"],
            "response": "Which region should I focus on?",
        }
    ]


def test_chat_stream_second_turn_emits_progress_source_and_done(client: TestClient) -> None:
    first = client.post("/v1/chat/stream", json={"message": "Research the EV charging market"})
    thread_id = parse_sse(first.text)[0]["thread_id"]

    second = client.post(
        "/v1/chat/stream", json={"thread_id": thread_id, "message": "Focus on the EU"}
    )

    events = parse_sse(second.text)
    assert {"type": "progress", "step": "Planning research approach"} in events
    assert {"type": "progress", "step": "Coordinating research"} in events
    assert {
        "type": "progress",
        "step": "researching",
        "detail": "Researching: EU",
    } in events
    assert {"type": "source", "topic": "EU", "summary": "EU findings"} in events
    assert events[-1] == {
        "type": "done",
        "thread_id": thread_id,
        "report": "# EV Charging Market Report",
    }

    audit = client.app.state.audit.records
    assert len(audit) == 2
    assert audit[1]["thread_id"] == thread_id
    assert audit[1]["operation"] == "chat_stream"
    assert audit[1]["status"] == "done"
    assert audit[1]["detail"] == {"report_chars": len(events[-1]["report"])}


def test_chat_persists_sources_same_as_chat_stream(client: TestClient) -> None:
    """/chat drives the same graph.astream as /chat/stream, so sources aren't dropped."""
    first = client.post("/v1/chat", json={"message": "Research the EV charging market"})
    thread_id = first.json()["data"]["thread_id"]
    client.post("/v1/chat", json={"thread_id": thread_id, "message": "Focus on the EU"})

    response = client.get(f"/v1/research/{thread_id}/report")

    assert response.status_code == 200
    assert response.json()["data"]["sources"] == [{"topic": "EU", "summary": "EU findings"}]


def test_chat_returns_502_and_marks_session_failed_on_graph_error(
    failing_client: TestClient,
) -> None:
    response = failing_client.post(
        "/v1/chat", json={"message": "Research the EV charging market"}
    )

    assert response.status_code == 502
    error = response.json()
    assert error["success"] is False
    assert error["data"]["code"] == 502

    sessions = failing_client.get("/v1/research/sessions").json()["data"]["sessions"]
    assert sessions[0]["status"] == "failed"

    status_body = failing_client.get(f"/v1/research/{sessions[0]['id']}").json()
    assert status_body["data"]["status"] == "failed"

    audit = failing_client.app.state.audit.records
    assert len(audit) == 1
    assert audit[0]["thread_id"] == sessions[0]["id"]
    assert audit[0]["operation"] == "chat"
    assert audit[0]["status"] == "failed"
    assert audit[0]["detail"] == {"error": "LLM provider unavailable"}


def test_chat_stream_emits_error_event_and_marks_session_failed(
    failing_client: TestClient,
) -> None:
    response = failing_client.post(
        "/v1/chat/stream", json={"message": "Research the EV charging market"}
    )

    assert response.status_code == 200
    events = parse_sse(response.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["message"] == "LLM provider unavailable"

    sessions = failing_client.get("/v1/research/sessions").json()["data"]["sessions"]
    assert sessions[0]["status"] == "failed"

    audit = failing_client.app.state.audit.records
    assert len(audit) == 1
    assert audit[0]["thread_id"] == sessions[0]["id"]
    assert audit[0]["operation"] == "chat_stream"
    assert audit[0]["status"] == "failed"
    assert audit[0]["detail"] == {"error": "LLM provider unavailable"}
