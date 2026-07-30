import {
  ApiEnvelope,
  ReportResponse,
  ResearchStatus,
  SessionSummary,
  StreamEvent,
} from "@/lib/types";

// Port 8001, not 8000: SigNoz's MCP server owns 8000. See backend/README.md.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001";

/** Unwrap the backend's `{success, data}` envelope, throwing the API's own error message
 * instead of a body-shape error when `success` is false. */
async function unwrap<T>(response: Response): Promise<T> {
  const body = (await response.json()) as ApiEnvelope<T>;
  if (!body.success) {
    throw new Error(body.data.message ?? body.data.description);
  }
  return body.data;
}

/**
 * POST one chat turn to /chat/stream and invoke `onEvent` for each SSE event as it arrives.
 * Resolves once the stream ends (after a terminal `clarify` or `done` event).
 */
export async function streamChat(
  message: string,
  threadId: string | null,
  onEvent: (event: StreamEvent) => void
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, message }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`/v1/chat/stream failed with status ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const raw of events) {
      const line = raw.trim();
      if (!line.startsWith("data: ")) continue;
      onEvent(JSON.parse(line.slice("data: ".length)) as StreamEvent);
    }
  }
}

/** List known research threads for the sidebar, pinned first then most recently started.
 * `query` filters by title (case-insensitive substring) for the search box. */
export async function listSessions(query?: string): Promise<SessionSummary[]> {
  const url = new URL(`${API_BASE_URL}/v1/research/sessions`);
  if (query) url.searchParams.set("q", query);
  const response = await fetch(url);
  const { sessions } = await unwrap<{ sessions: SessionSummary[] }>(response);
  return sessions;
}

/** Rename a session's sidebar title. */
export async function renameSession(threadId: string, title: string): Promise<SessionSummary> {
  const response = await fetch(`${API_BASE_URL}/v1/research/sessions/${threadId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return unwrap<SessionSummary>(response);
}

/** Pin or unpin a session so it sorts to the top of the sidebar. */
export async function setSessionPinned(
  threadId: string,
  pinned: boolean
): Promise<SessionSummary> {
  const response = await fetch(`${API_BASE_URL}/v1/research/sessions/${threadId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pinned }),
  });
  return unwrap<SessionSummary>(response);
}

/** Thrown by `deleteSession` when the backend refuses because the session's turn is still
 * `queued`/`running` (409) — distinct from other failures so the UI can explain why. */
export class SessionInProgressError extends Error {}

/** Permanently delete a session from the sidebar. */
export async function deleteSession(threadId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/v1/research/sessions/${threadId}`, {
    method: "DELETE",
  });
  if (response.status === 409) {
    throw new SessionInProgressError("Research is still in progress for this session");
  }
  if (!response.ok) {
    throw new Error(`Failed to delete session ${threadId} (status ${response.status})`);
  }
}

/** Read one thread's current status straight off the graph's checkpoint. */
export async function getResearchStatus(threadId: string): Promise<ResearchStatus> {
  const response = await fetch(`${API_BASE_URL}/v1/research/${threadId}`);
  return unwrap<ResearchStatus>(response);
}

/** Fetch a completed thread's report and sources, to reopen the drawer without a rerun. */
export async function getResearchReport(threadId: string): Promise<ReportResponse> {
  const response = await fetch(`${API_BASE_URL}/v1/research/${threadId}/report`);
  return unwrap<ReportResponse>(response);
}
