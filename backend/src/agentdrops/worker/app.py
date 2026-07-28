"""Worker process entrypoint: `celery -A agentdrops.worker.app worker` imports this module.

Configuring the Celery app and importing the task module (to register it) both need to happen
here rather than in `celery_app.py`, so that module can stay import-safe without a populated
environment (see its docstring) while this one — only ever run by the `celery` CLI in a real
worker process — is where settings are actually required.
"""

from celery.signals import worker_process_init, worker_process_shutdown

from agentdrops.config import get_settings
from agentdrops.observability.setup import Providers, configure_observability
from agentdrops.worker.celery_app import celery_app, configure_celery
from agentdrops.worker.tasks import run_turn_task  # noqa: F401  (registers the task)

configure_celery(get_settings())

_providers: Providers = Providers()


@worker_process_init.connect  # type: ignore[untyped-decorator]
def _init_observability(**_kwargs: object) -> None:
    """Configure telemetry inside each forked worker child, not the pre-fork parent module
    import — the OTel exporter's gRPC channel and background export thread are a documented
    fork-safety hazard if created once in the parent and inherited into every child. `celery -A
    ... worker` defaults to the prefork pool, which sends this signal once per child after it
    forks — the standard hook for per-child resource setup.

    Caveat: under `--pool=solo` (no forking, single-process — dev/debug use only) Celery does
    not send this signal at all, so telemetry silently stays unconfigured in that mode. This
    project's `Makefile` `worker` target uses the default prefork pool, so that's the accepted
    tradeoff, not a gap in the deployed configuration.
    """
    global _providers
    _providers = configure_observability(get_settings())


@worker_process_shutdown.connect  # type: ignore[untyped-decorator]
def _flush_observability(**_kwargs: object) -> None:
    """Flush pending telemetry when the worker process exits — without this the last run's
    spans die with the process, same reasoning as `main.py`'s lifespan `finally` block."""
    _providers.shutdown()


__all__ = ["celery_app"]
