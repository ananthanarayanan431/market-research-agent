"""One OTel `Resource` shared by all three signals.

Traces, metrics and logs must carry *identical* resource attributes or SigNoz treats them as
separate services and cannot correlate a log line to the span it was emitted from.
"""

from importlib.metadata import PackageNotFoundError, version

from opentelemetry.sdk.resources import (
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)


def _package_version() -> str:
    try:
        return version("agentdrops")
    except PackageNotFoundError:  # running from a source tree that was never installed
        return "0.0.0+unknown"


def build_resource(service_name: str, environment: str = "development") -> Resource:
    """Build the resource identifying this service in SigNoz."""
    return Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: _package_version(),
            DEPLOYMENT_ENVIRONMENT: environment,
        }
    )
