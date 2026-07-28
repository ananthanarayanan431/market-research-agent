"""Worker process entrypoint: `celery -A agentdrops.worker.app worker` imports this module.

Configuring the Celery app and importing the task module (to register it) both need to happen
here rather than in `celery_app.py`, so that module can stay import-safe without a populated
environment (see its docstring) while this one — only ever run by the `celery` CLI in a real
worker process — is where settings are actually required.
"""

from celery.signals import worker_process_shutdown

from agentdrops.config import get_settings
from agentdrops.observability.setup import configure_observability
from agentdrops.worker.celery_app import celery_app, configure_celery
from agentdrops.worker.tasks import run_turn_task  # noqa: F401  (registers the task)

_settings = get_settings()
configure_celery(_settings)
_providers = configure_observability(_settings)


@worker_process_shutdown.connect  # type: ignore[untyped-decorator]
def _flush_observability(**_kwargs: object) -> None:
    """Flush pending telemetry when the worker process exits — without this the last run's
    spans die with the process, same reasoning as `main.py`'s lifespan `finally` block."""
    _providers.shutdown()


__all__ = ["celery_app"]
