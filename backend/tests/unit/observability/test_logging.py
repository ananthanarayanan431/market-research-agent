import logging

from opentelemetry.sdk.resources import SERVICE_NAME

from agentdrops.observability.logging import (
    _run_id_var,
    _RunIdFilter,
    bind_run_id,
    configure_logging,
    get_logger,
)


def test_run_id_filter_stamps_record_with_bound_run_id() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", None, None)
    with bind_run_id("run-123"):
        _RunIdFilter().filter(record)
    assert record.run_id == "run-123"  # type: ignore[attr-defined]


def test_run_id_filter_stamps_none_when_unbound() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", None, None)
    _RunIdFilter().filter(record)
    assert record.run_id is None  # type: ignore[attr-defined]


def test_bind_run_id_resets_after_context_exits() -> None:
    with bind_run_id("run-123"):
        assert _run_id_var.get() == "run-123"
    assert _run_id_var.get() is None


def test_bind_run_id_restores_outer_value_when_nested() -> None:
    with bind_run_id("outer"):
        with bind_run_id("inner"):
            assert _run_id_var.get() == "inner"
        assert _run_id_var.get() == "outer"
    assert _run_id_var.get() is None


def test_get_logger_returns_a_stdlib_logger() -> None:
    logger = get_logger("agentdrops.test")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "agentdrops.test"


def test_configure_logging_returns_provider_with_service_name_resource() -> None:
    provider = configure_logging(service_name="agentdrops-test", otlp_endpoint="http://localhost:4317")
    assert provider.resource.attributes[SERVICE_NAME] == "agentdrops-test"
