import json

import pytest

from agentdrops.logging import bind_run_id, configure_logging, get_logger


def test_configure_logging_emits_json_with_bound_run_id(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO")
    logger = get_logger("test")

    with bind_run_id("run-123"):
        logger.info("research_started", topic="AI note-taking apps")

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])

    assert payload["event"] == "research_started"
    assert payload["run_id"] == "run-123"
    assert payload["topic"] == "AI note-taking apps"
    assert payload["level"] == "info"


def test_bind_run_id_unbinds_after_context_exits(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO")
    logger = get_logger("test")

    with bind_run_id("run-123"):
        pass
    logger.info("after_context")

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])
    assert "run_id" not in payload
