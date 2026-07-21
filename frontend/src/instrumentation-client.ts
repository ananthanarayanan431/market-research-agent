// Runs after the document loads but before React hydrates (Next.js `instrumentation-client`
// convention), so document-load and every subsequent fetch are traced from the first paint.
import { initTelemetry } from "@/lib/telemetry";

initTelemetry();
