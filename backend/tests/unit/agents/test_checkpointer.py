from agentdrops.agents.checkpointer import strip_asyncpg_dialect


def test_strip_asyncpg_dialect_removes_the_sqlalchemy_prefix() -> None:
    assert (
        strip_asyncpg_dialect("postgresql+asyncpg://u:p@localhost:5432/agentdrops")
        == "postgresql://u:p@localhost:5432/agentdrops"
    )


def test_strip_asyncpg_dialect_is_a_noop_if_already_plain() -> None:
    assert (
        strip_asyncpg_dialect("postgresql://u:p@localhost:5432/agentdrops")
        == "postgresql://u:p@localhost:5432/agentdrops"
    )
