"""Real-minio integration fixture (the docker-compose instance), auto-skipped when unreachable —
same shape as tests/unit/repository/conftest.py's Postgres auto-skip."""

import uuid

import pytest
from minio.error import S3Error
from urllib3.exceptions import MaxRetryError

from agentdrops.storage.contexthub import ContextHubStorage
from tests.unit.agents.conftest import make_settings


@pytest.fixture
def contexthub_storage() -> ContextHubStorage:
    settings = make_settings(minio_contexthub_bucket=f"contexthub-test-{uuid.uuid4().hex[:8]}")
    storage = ContextHubStorage(settings)
    try:
        storage.client.bucket_exists(settings.minio_contexthub_bucket)
    except (MaxRetryError, S3Error) as exc:
        pytest.skip(f"minio not reachable at {settings.minio_endpoint}: {exc}")
    return storage
