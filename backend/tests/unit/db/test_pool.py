from agentdrops.db.pool import _asyncpg_dsn


def test_strips_sqlalchemy_asyncpg_driver_marker() -> None:
    url = "postgresql+asyncpg://agentdrops:agentdrops@localhost:5432/agentdrops"
    assert _asyncpg_dsn(url) == "postgresql://agentdrops:agentdrops@localhost:5432/agentdrops"


def test_leaves_plain_postgresql_url_unchanged() -> None:
    url = "postgresql://agentdrops:agentdrops@localhost:5432/agentdrops"
    assert _asyncpg_dsn(url) == url
