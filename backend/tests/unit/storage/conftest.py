"""Real-minio integration fixture (the docker-compose instance), auto-skipped when unreachable —
same shape as tests/unit/repository/conftest.py's Postgres auto-skip."""

import uuid
from collections.abc import Iterator

import pytest
from urllib3.exceptions import MaxRetryError

from agentdrops.storage.contexthub import ContextHubStorage
from tests.unit.agents.conftest import make_settings


@pytest.fixture
def contexthub_storage() -> Iterator[ContextHubStorage]:
    settings = make_settings(minio_contexthub_bucket=f"contexthub-test-{uuid.uuid4().hex[:8]}")
    storage = ContextHubStorage(settings)
    try:
        storage.client.bucket_exists(settings.minio_contexthub_bucket)
    except MaxRetryError as exc:
        pytest.skip(f"minio not reachable at {settings.minio_endpoint}: {exc}")

    try:
        yield storage
    finally:
        bucket = settings.minio_contexthub_bucket
        if storage.client.bucket_exists(bucket):
            for obj in storage.client.list_objects(bucket, recursive=True):
                storage.client.remove_object(bucket, obj.object_name)
            storage.client.remove_bucket(bucket)
