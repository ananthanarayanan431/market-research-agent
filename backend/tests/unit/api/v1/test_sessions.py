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
    assert all(s["pinned"] is False for s in sessions)


async def test_list_sessions_filters_by_query(client: TestClient) -> None:
    await _run_turn(client, str(uuid.uuid4()), "Research the EV charging market")
    await _run_turn(client, str(uuid.uuid4()), "Research the fintech market")

    response = client.get("/v1/research/sessions", params={"q": "fintech"})

    assert response.status_code == 200
    titles = [s["title"] for s in response.json()["data"]["sessions"]]
    assert titles == ["Research the fintech market"]


async def test_update_session_renames_it(client: TestClient) -> None:
    thread_id = str(uuid.uuid4())
    await _run_turn(client, thread_id, "Research the EV charging market")

    response = client.patch(
        f"/v1/research/sessions/{thread_id}", json={"title": "EV market deep dive"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["title"] == "EV market deep dive"


async def test_update_session_pins_it(client: TestClient) -> None:
    thread_id = str(uuid.uuid4())
    await _run_turn(client, thread_id, "Research the EV charging market")

    response = client.patch(f"/v1/research/sessions/{thread_id}", json={"pinned": True})

    assert response.status_code == 200
    assert response.json()["data"]["pinned"] is True


async def test_update_session_404s_for_unknown_thread(client: TestClient) -> None:
    response = client.patch("/v1/research/sessions/does-not-exist", json={"title": "New title"})

    assert response.status_code == 404


async def test_delete_session_removes_it_from_the_list(client: TestClient) -> None:
    thread_id = str(uuid.uuid4())
    await _run_turn(client, thread_id, "Research the EV charging market")

    response = client.delete(f"/v1/research/sessions/{thread_id}")

    assert response.status_code == 204
    assert client.get("/v1/research/sessions").json()["data"]["sessions"] == []


async def test_delete_session_404s_for_unknown_thread(client: TestClient) -> None:
    response = client.delete("/v1/research/sessions/does-not-exist")

    assert response.status_code == 404


async def test_delete_session_409s_while_running(client: TestClient) -> None:
    thread_id = str(uuid.uuid4())
    await client.app.state.sessions.touch(thread_id, title="EV charging market")
    await client.app.state.sessions.set_status(thread_id, "running")

    response = client.delete(f"/v1/research/sessions/{thread_id}")

    assert response.status_code == 409
    assert client.get("/v1/research/sessions").json()["data"]["sessions"][0]["id"] == thread_id


async def test_delete_session_409s_while_queued(client: TestClient) -> None:
    thread_id = str(uuid.uuid4())
    await client.app.state.sessions.touch(thread_id, title="EV charging market")
    await client.app.state.sessions.set_status(thread_id, "queued")

    response = client.delete(f"/v1/research/sessions/{thread_id}")

    assert response.status_code == 409
