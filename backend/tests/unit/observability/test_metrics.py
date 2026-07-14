from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME

from agentdrops.observability.metrics import configure_metrics, get_meter, record_tool_call


def test_record_tool_call_emits_a_histogram_data_point(metric_reader: InMemoryMetricReader) -> None:
    record_tool_call("exa", 0.42, success=True)

    data = metric_reader.get_metrics_data()
    assert data is not None
    metric_names = [
        metric.name
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    ]
    assert "agentdrops.tool_call.duration" in metric_names


def test_get_meter_returns_a_meter() -> None:
    meter = get_meter("agentdrops.test")
    assert meter is not None


def test_configure_metrics_returns_provider_with_service_name_resource() -> None:
    provider = configure_metrics(service_name="agentdrops-test", otlp_endpoint="http://localhost:4317")
    assert provider._sdk_config.resource.attributes[SERVICE_NAME] == "agentdrops-test"
