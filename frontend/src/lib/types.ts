export type Phase = "idle" | "clarifying" | "running" | "complete";

export type Message =
  | { id: string; kind: "user"; text: string }
  | { id: string; kind: "assistant"; text: string };

export type ProgressStep = {
  title: string;
  detail?: string;
  topic?: string;
  active: boolean;
};

export type ResearchSource = {
  topic: string;
  summary: string;
};

export type StreamEvent =
  | { type: "progress"; step: string; detail?: string; topic?: string }
  | { type: "source"; topic: string; summary: string }
  | { type: "source_url"; topic: string; tool_name: string; title: string; url: string }
  | { type: "clarify"; thread_id: string; response: string; suggestions: string[] }
  | { type: "done"; thread_id: string; report: string }
  | { type: "error"; thread_id: string; message: string };

export type ResearchStatusValue = "queued" | "clarifying" | "running" | "done" | "failed";

export type SessionSummary = {
  id: string;
  title: string;
  created_at: string;
  status: ResearchStatusValue;
  pinned: boolean;
};

export type ResearchStatus = {
  thread_id: string;
  status: ResearchStatusValue;
  research_brief: string | null;
  report: string | null;
  clarify_question: string | null;
  clarify_suggestions: string[];
};

export type ReportResponse = {
  thread_id: string;
  report: string;
  sources: ResearchSource[];
};

/** The `{code, description, message}` body every non-2xx REST response returns as `data`. */
export type ApiError = {
  code: number;
  description: string;
  message: string | null;
};

/** The `{success, data}` envelope every plain-JSON REST endpoint wraps its body in. SSE events
 * on /v1/chat/stream are a separate protocol (see StreamEvent) and are not wrapped this way. */
export type ApiEnvelope<T> =
  | { success: true; data: T }
  | { success: false; data: ApiError };

export type ContextHubDocumentStatus = "processing" | "ready" | "failed";

export type ContextHubDocument = {
  id: string;
  title: string;
  source_type: "file" | "url";
  status: ContextHubDocumentStatus;
  error: string | null;
  created_at: string;
};
