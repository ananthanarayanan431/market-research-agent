from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import Histogram, Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource


def configure_metrics(
    service_name: str, otlp_endpoint: str, resource: Resource | None = None
) -> MeterProvider:
    resource = resource or Resource.create({SERVICE_NAME: service_name})
    exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
    reader = PeriodicExportingMetricReader(exporter)
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    return provider


def get_meter(name: str) -> Meter:
    return metrics.get_meter(name)


_tool_call_duration: Histogram | None = None


def record_tool_call(tool_name: str, duration_seconds: float, *, success: bool) -> None:
    global _tool_call_duration
    if _tool_call_duration is None:
        _tool_call_duration = get_meter("agentdrops").create_histogram(
            name="agentdrops.tool_call.duration",
            unit="s",
            description="Duration of an external tool call (search tool or LLM call).",
        )
    _tool_call_duration.record(
        duration_seconds, attributes={"tool_name": tool_name, "success": success}
    )
