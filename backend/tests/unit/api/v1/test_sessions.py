import uuid

from fastapi.testclient import TestClient

from tests.unit.api.v1.conftest import run_turn as _run_turn


async def test_list_sessions_returns_known_threads_newest_first(client: TestClient) -> None:
    await _run_turn(client, str(uuid.uuid4()), "Research the EV charging market")
    await _run_turn(client, str(uuid.uuid4()), "Research the fintech market")

    response = client.get("/v1/research/sessions")

    assert response.status_code == 200
    sessions = response.json()["data"]["sessions"]
    titles = [s["title"] for s in sessions]
    assert titles == ["Research the fintech market", "Research the EV charging market"]
    assert all(s["status"] == "clarifying" for s in sessions)
