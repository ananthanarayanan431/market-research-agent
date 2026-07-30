"""Shared Celery application. Broker/backend are configured explicitly at process startup
(API lifespan, worker entrypoint) rather than at import time, so importing this module never
requires a populated environment — the same lazy-construction shape as `config.get_settings()`.
"""

from celery import Celery

from agentdrops.config import Settings

celery_app = Celery("agentdrops")


def configure_celery(settings: Settings) -> None:
    celery_app.conf.broker_url = settings.redis_url
    celery_app.conf.result_backend = settings.redis_url
