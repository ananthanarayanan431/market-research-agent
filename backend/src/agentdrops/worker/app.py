"""Worker process entrypoint: `celery -A agentdrops.worker.app worker` imports this module.

Configuring the Celery app and importing the task module (to register it) both need to happen
here rather than in `celery_app.py`, so that module can stay import-safe without a populated
environment (see its docstring) while this one — only ever run by the `celery` CLI in a real
worker process — is where settings are actually required.
"""

from agentdrops.config import get_settings
from agentdrops.worker.celery_app import celery_app, configure_celery
from agentdrops.worker.tasks import run_turn_task  # noqa: F401  (registers the task)

configure_celery(get_settings())

__all__ = ["celery_app"]
