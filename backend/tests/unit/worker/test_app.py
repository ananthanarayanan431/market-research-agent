import importlib

import pytest

import agentdrops.config as config_module
import agentdrops.worker.app as app_module
import agentdrops.worker.celery_app as celery_app_module
from agentdrops.observability.setup import Providers
from tests.unit.agents.conftest import make_settings


def test_importing_worker_app_configures_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    """`configure_celery` runs at import time, in the pre-fork parent — Celery's own config is
    plain data with no fork-safety concern. Observability is configured separately, per forked
    child, via `worker_process_init` (see the two tests below), not at import time.
    """
    calls: list[str] = []
    monkeypatch.setattr(config_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        celery_app_module, "configure_celery", lambda settings: calls.append("celery")
    )

    importlib.reload(app_module)

    assert calls == ["celery"]


def test_worker_process_init_configures_observability(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(app_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        app_module,
        "configure_observability",
        lambda settings: (calls.append("observability"), Providers())[1],
    )

    app_module._init_observability()

    assert calls == ["observability"]
    assert isinstance(app_module._providers, Providers)


def test_worker_process_shutdown_flushes_observability_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdown_calls: list[str] = []

    class _RecordingProviders(Providers):
        def shutdown(self) -> None:
            shutdown_calls.append("shutdown")

    monkeypatch.setattr(app_module, "_providers", _RecordingProviders())

    app_module._flush_observability()

    assert shutdown_calls == ["shutdown"]
