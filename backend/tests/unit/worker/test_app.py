import sys

import pytest

import agentdrops.config as config_module
import agentdrops.worker.celery_app as celery_app_module
from agentdrops.observability.setup import Providers
from tests.unit.agents.conftest import make_settings


def _import_worker_app() -> object:
    """Force a fresh execution of `agentdrops.worker.app`'s module body under whatever patches
    are currently active — dropping any cached import first, rather than `importlib.reload`,
    so the module-level `configure_celery(get_settings())` call runs exactly once per test
    regardless of whether an earlier test already imported the module."""
    sys.modules.pop("agentdrops.worker.app", None)
    import agentdrops.worker.app as app_module

    return app_module


def test_importing_worker_app_configures_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    """`configure_celery` runs at import time, in the pre-fork parent — Celery's own config is
    plain data with no fork-safety concern. Observability is configured separately, per forked
    child, via `worker_process_init` (see the two tests below), not at import time.

    `agentdrops.worker.app` is imported here, inside the test, only after the patches below are
    in place — importing it at module scope would run the real `agentdrops.config.get_settings()`
    during collection, which fails fast without a populated `.env`/environment (the same
    requirement production's `celery -A ... worker` relies on, but not one test collection should
    inherit).
    """
    calls: list[str] = []
    monkeypatch.setattr(config_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        celery_app_module, "configure_celery", lambda settings: calls.append("celery")
    )

    _import_worker_app()

    assert calls == ["celery"]


def test_worker_process_init_configures_observability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(celery_app_module, "configure_celery", lambda settings: None)

    app_module = _import_worker_app()

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
    monkeypatch.setattr(config_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(celery_app_module, "configure_celery", lambda settings: None)

    app_module = _import_worker_app()

    shutdown_calls: list[str] = []

    class _RecordingProviders(Providers):
        def shutdown(self) -> None:
            shutdown_calls.append("shutdown")

    monkeypatch.setattr(app_module, "_providers", _RecordingProviders())

    app_module._flush_observability()

    assert shutdown_calls == ["shutdown"]
