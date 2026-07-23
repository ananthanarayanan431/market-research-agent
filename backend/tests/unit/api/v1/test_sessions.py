import uuid

from fastapi.testclient import TestClient


async def _run_turn(
    client: TestClient, thread_id: str, message: str, *, operation: str = "chat"
) -> None:
    """Directly drive `ChatService.run_turn` to simulate what the background worker does —
    `/chat` now only enqueues a Celery task rather than executing the graph inline, so this
    listing test populates state the same way the worker would."""
    service = client.app.state.chat_service
    async for _ in service.run_turn(thread_id, message, operation=operation):
        pass


async def test_list_sessions_returns_known_threads_newest_first(client: TestClient) -> None:
    await _run_turn(client, str(uuid.uuid4()), "Research the EV charging market")
    await _run_turn(client, str(uuid.uuid4()), "Research the fintech market")

    response = client.get("/v1/research/sessions")

    assert response.status_code == 200
    sessions = response.json()["data"]["sessions"]
    titles = [s["title"] for s in sessions]
    assert titles == ["Research the fintech market", "Research the EV charging market"]
    assert all(s["status"] == "clarifying" for s in sessions)
