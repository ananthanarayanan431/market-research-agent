import pytest
from minio.error import S3Error

from agentdrops.storage.contexthub import ContextHubStorage


async def test_put_then_get_roundtrips_bytes(contexthub_storage: ContextHubStorage) -> None:
    await contexthub_storage.put("docs/one.txt", b"hello world", "text/plain")

    result = await contexthub_storage.get("docs/one.txt")

    assert result == b"hello world"


async def test_delete_removes_the_object(contexthub_storage: ContextHubStorage) -> None:
    await contexthub_storage.put("docs/two.txt", b"gone soon", "text/plain")

    await contexthub_storage.delete("docs/two.txt")

    with pytest.raises(S3Error) as exc_info:
        await contexthub_storage.get("docs/two.txt")
    assert exc_info.value.code == "NoSuchKey"
