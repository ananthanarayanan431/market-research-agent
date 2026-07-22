from fastapi.testclient import TestClient


def test_list_sessions_returns_known_threads_newest_first(client: TestClient) -> None:
    client.post("/v1/chat", json={"message": "Research the EV charging market"})
    client.post("/v1/chat", json={"message": "Research the fintech market"})

    response = client.get("/v1/research/sessions")

    assert response.status_code == 200
    sessions = response.json()["data"]["sessions"]
    titles = [s["title"] for s in sessions]
    assert titles == ["Research the fintech market", "Research the EV charging market"]
    assert all(s["status"] == "clarifying" for s in sessions)
