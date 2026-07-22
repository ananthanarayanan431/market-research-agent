from agentdrops.worker.celery_app import celery_app, configure_celery
from tests.unit.agents.conftest import make_settings


def test_configure_celery_sets_broker_and_backend_from_settings() -> None:
    settings = make_settings(redis_url="redis://example-host:6379/2")

    configure_celery(settings)

    assert celery_app.conf.broker_url == "redis://example-host:6379/2"
    assert celery_app.conf.result_backend == "redis://example-host:6379/2"
