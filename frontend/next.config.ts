import type { NextConfig } from "next";

// Browsers cannot POST OTLP straight to SigNoz's collector: it's a cross-origin request the
// collector answers without CORS headers, so the browser blocks the export. Instead the browser
// ships to a same-origin path (/otel/...) and Next proxies it to the collector server-side — no
// CORS, and the collector's address never leaves the server. OTEL_COLLECTOR_URL points at the
// OTLP/HTTP endpoint (4318); default is the local Foundry deployment.
const COLLECTOR = process.env.OTEL_COLLECTOR_URL ?? "http://localhost:4318";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/otel/:path*", destination: `${COLLECTOR}/:path*` }];
  },
};

export default nextConfig;
