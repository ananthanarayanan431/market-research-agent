import { Span, SpanStatusCode, trace } from "@opentelemetry/api";
import { ZoneContextManager } from "@opentelemetry/context-zone";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { registerInstrumentations } from "@opentelemetry/instrumentation";
import { DocumentLoadInstrumentation } from "@opentelemetry/instrumentation-document-load";
import { FetchInstrumentation } from "@opentelemetry/instrumentation-fetch";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BatchSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { WebTracerProvider } from "@opentelemetry/sdk-trace-web";
import {
  ATTR_SERVICE_NAME,
  ATTR_SERVICE_VERSION,
} from "@opentelemetry/semantic-conventions";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001";

// Browsers cannot speak OTLP/gRPC (backend uses gRPC :4317) and a direct cross-origin POST to
// the collector's HTTP port is blocked by CORS. So spans go to a same-origin path that
// next.config.ts rewrites to the collector's OTLP/HTTP endpoint (:4318). Override only if you
// front the collector yourself with CORS configured.
const OTLP_ENDPOINT =
  process.env.NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT ?? "/otel";

const SERVICE_NAME =
  process.env.NEXT_PUBLIC_OTEL_SERVICE_NAME ?? "agentdrops-frontend";

// Matches the Python side's DEPLOYMENT_ENVIRONMENT key rather than the newer
// `deployment.environment.name` semconv attribute, so both services land on the same
// dimension in SigNoz instead of splitting into two.
const ATTR_DEPLOYMENT_ENVIRONMENT = "deployment.environment";

let started = false;

/**
 * Start browser tracing and ship spans to SigNoz.
 *
 * Safe to call more than once — React strict mode double-invokes effects, and a second
 * provider would double-report every span.
 */
export function initTelemetry(): void {
  if (started || typeof window === "undefined") return;
  started = true;

  try {
    const provider = new WebTracerProvider({
      resource: resourceFromAttributes({
        [ATTR_SERVICE_NAME]: SERVICE_NAME,
        [ATTR_SERVICE_VERSION]: process.env.NEXT_PUBLIC_APP_VERSION ?? "0.1.0",
        [ATTR_DEPLOYMENT_ENVIRONMENT]:
          process.env.NEXT_PUBLIC_OTEL_ENVIRONMENT ?? "development",
      }),
      spanProcessors: [
        new BatchSpanProcessor(
          new OTLPTraceExporter({ url: `${OTLP_ENDPOINT}/v1/traces` })
        ),
      ],
    });

    // ZoneContextManager keeps the active span attached across await boundaries, which is what
    // lets the long-lived /chat/stream read loop stay parented to the span that started it.
    provider.register({ contextManager: new ZoneContextManager() });

    registerInstrumentations({
      instrumentations: [
        new DocumentLoadInstrumentation(),
        new FetchInstrumentation({
          // Without this the browser never attaches `traceparent` to cross-origin requests, and
          // the backend would start a brand-new trace instead of continuing this one — the
          // frontend and backend halves of a research run would never join up in SigNoz.
          propagateTraceHeaderCorsUrls: [new RegExp(escapeRegExp(API_BASE_URL))],
          clearTimingResources: true,
        }),
      ],
    });
  } catch (error) {
    // Telemetry must never take the app down with it.
    console.error("[telemetry] failed to initialize", error);
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Run `fn` inside a span named `name`, recording any thrown error on it.
 *
 * Wraps a whole user action (a research submission) so the auto-instrumented fetch spans nest
 * underneath it, rather than floating as unattached top-level spans in SigNoz.
 */
export async function withSpan<T>(
  name: string,
  attributes: Record<string, string | number | boolean>,
  fn: (span: Span) => Promise<T>
): Promise<T> {
  const tracer = trace.getTracer("agentdrops-frontend");
  return tracer.startActiveSpan(name, { attributes }, async (span) => {
    try {
      return await fn(span);
    } catch (error) {
      span.recordException(error as Error);
      span.setStatus({ code: SpanStatusCode.ERROR, message: String(error) });
      throw error;
    } finally {
      span.end();
    }
  });
}
