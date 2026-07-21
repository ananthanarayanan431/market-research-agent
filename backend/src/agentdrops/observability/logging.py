import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

_run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id_var.get()
        return True


def configure_logging(
    service_name: str,
    otlp_endpoint: str,
    level: str = "INFO",
    resource: Resource | None = None,
) -> LoggerProvider:
    numeric_level = _LEVEL_MAP.get(level.upper(), logging.INFO)
    resource = resource or Resource.create({SERVICE_NAME: service_name})
    provider = LoggerProvider(resource=resource)
    exporter = OTLPLogExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

    handler = LoggingHandler(level=numeric_level, logger_provider=provider)
    handler.addFilter(_RunIdFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.addHandler(handler)
    return provider


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def bind_run_id(run_id: str) -> Iterator[None]:
    token = _run_id_var.set(run_id)
    try:
        yield
    finally:
        _run_id_var.reset(token)
