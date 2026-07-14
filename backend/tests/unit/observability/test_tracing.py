from opentelemetry.sdk.resources import SERVICE_NAME
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agentdrops.observability.tracing import configure_tracing, get_tracer, traced_span


def test_traced_span_records_a_finished_span_with_attributes(
    span_exporter: InMemorySpanExporter,
) -> None:
    with traced_span("supervisor_node", run_id="run-123", iteration=1):
        pass

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "supervisor_node"
    assert spans[0].attributes is not None
    assert spans[0].attributes["run_id"] == "run-123"
    assert spans[0].attributes["iteration"] == 1


def test_traced_span_records_exception_and_still_ends_span(
    span_exporter: InMemorySpanExporter,
) -> None:
    try:
        with traced_span("failing_node"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "failing_node"


def test_get_tracer_returns_a_tracer() -> None:
    tracer = get_tracer("agentdrops.test")
    assert tracer is not None


def test_configure_tracing_returns_provider_with_service_name_resource() -> None:
    provider = configure_tracing(service_name="agentdrops-test", otlp_endpoint="http://localhost:4317")
    assert provider.resource.attributes[SERVICE_NAME] == "agentdrops-test"
