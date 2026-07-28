import importlib

import pytest

import agentdrops.config as config_module
import agentdrops.observability.setup as observability_setup_module
import agentdrops.worker.app as app_module
import agentdrops.worker.celery_app as celery_app_module
from agentdrops.observability.setup import Providers
from tests.unit.agents.conftest import make_settings


def test_importing_worker_app_configures_celery_and_observability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`worker/app.py` configures Celery and observability at import time (there is no
    lifespan-style hook for a Celery worker process), so this is exercised via
    `importlib.reload` rather than a normal function call.

    Patching must target the *origin* modules (`agentdrops.config`, `agentdrops.worker.
    celery_app`, `agentdrops.observability.setup`), not `app_module` itself: `reload()`
    re-executes `worker/app.py`'s top-level `from ... import ...` statements, which re-bind
    fresh (unpatched) names into `app_module`'s namespace before its own module-level code
    runs — so patching `app_module.get_settings` etc. directly would be silently undone by
    the reload before it ever took effect.
    """
    calls: list[str] = []
    monkeypatch.setattr(config_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        celery_app_module, "configure_celery", lambda settings: calls.append("celery")
    )
    monkeypatch.setattr(
        observability_setup_module,
        "configure_observability",
        lambda settings: calls.append("observability") or Providers(),
    )

    importlib.reload(app_module)

    assert calls == ["celery", "observability"]
