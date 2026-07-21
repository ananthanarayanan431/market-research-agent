"""One call that turns on every signal and every instrumentor, wired to SigNoz.

Called once from the FastAPI lifespan. Everything downstream (graph nodes, search tools) just
uses the OTel global providers this installs, so nothing else needs an observability import.
"""

import logging
from dataclasses import dataclass

from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider

from agentdrops.config import Settings
from agentdrops.observability.logging import configure_logging
from agentdrops.observability.metrics import configure_metrics
from agentdrops.observability.resource import build_resource
from agentdrops.observability.tracing import configure_tracing

logger = logging.getLogger(__name__)


@dataclass
class Providers:
    """The three SDK providers, held so the lifespan can flush them on shutdown."""

    tracer: TracerProvider | None = None
    meter: MeterProvider | None = None
    logger: LoggerProvider | None = None

    def shutdown(self) -> None:
        """Flush pending telemetry. Without this, the last run's spans die with the process —
        exactly the run someone is most likely watching in SigNoz after hitting Ctrl-C."""
        for provider in (self.tracer, self.meter, self.logger):
            if provider is not None:
                try:
                    provider.shutdown()
                except Exception:  # never let telemetry teardown break app shutdown
                    logger.warning("otel provider shutdown failed", exc_info=True)


def _instrument_langchain() -> None:
    """Emit GenAI-convention spans for every LangChain/LangGraph invocation.

    This is what makes the agent legible in SigNoz: one span per graph node, per LLM call and
    per tool call, carrying model name, prompts and token counts — rather than a single opaque
    `POST /chat` span covering a multi-minute research run.
    """
    from openinference.instrumentation.langchain import LangChainInstrumentor

    LangChainInstrumentor().instrument()


def configure_observability(settings: Settings) -> Providers:
    """Configure traces, metrics and logs, plus FastAPI/httpx/LangChain instrumentation."""
    if not settings.otel_enabled:
        logger.info("telemetry disabled (otel_enabled=false)")
        return Providers()

    resource = build_resource(settings.otel_service_name, settings.otel_environment)
    endpoint = settings.otel_exporter_otlp_endpoint

    providers = Providers(
        tracer=configure_tracing(settings.otel_service_name, endpoint, resource=resource),
        meter=configure_metrics(settings.otel_service_name, endpoint, resource=resource),
        logger=configure_logging(
            settings.otel_service_name, endpoint, level=settings.log_level, resource=resource
        ),
    )

    # httpx is instrumented at the class level so it covers the shared AsyncClient built in the
    # lifespan — that one client is what every search tool issues its requests through.
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()
    _instrument_langchain()

    logger.info(
        "telemetry configured",
        extra={"otlp_endpoint": endpoint, "service": settings.otel_service_name},
    )
    return providers


def instrument_fastapi(app: object) -> None:
    """Add request spans to the app, continuing any trace the frontend started.

    Separate from `configure_observability` because it must run against the app object, and
    after the tracer provider exists.
    """
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    # /health is excluded so container healthchecks don't flood the trace list with noise.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health")  # type: ignore[arg-type]


__all__ = ["Providers", "configure_observability", "instrument_fastapi"]
