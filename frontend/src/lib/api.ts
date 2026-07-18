import {
  ReportResponse,
  ResearchStatus,
  SessionSummary,
  StreamEvent,
} from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * POST one chat turn to /chat/stream and invoke `onEvent` for each SSE event as it arrives.
 * Resolves once the stream ends (after a terminal `clarify` or `done` event).
 */
export async function streamChat(
  message: string,
  threadId: string | null,
  onEvent: (event: StreamEvent) => void
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, message }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`/chat/stream failed with status ${response.status}`);
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

/** List every known research thread, most recently started first, for the sidebar. */
export async function listSessions(): Promise<SessionSummary[]> {
  const response = await fetch(`${API_BASE_URL}/research/sessions`);
  if (!response.ok) {
    throw new Error(`/research/sessions failed with status ${response.status}`);
  }
  const body = (await response.json()) as { sessions: SessionSummary[] };
  return body.sessions;
}

/** Read one thread's current status straight off the graph's checkpoint. */
export async function getResearchStatus(threadId: string): Promise<ResearchStatus> {
  const response = await fetch(`${API_BASE_URL}/research/${threadId}`);
  if (!response.ok) {
    throw new Error(`/research/${threadId} failed with status ${response.status}`);
  }
  return (await response.json()) as ResearchStatus;
}

/** Fetch a completed thread's report and sources, to reopen the drawer without a rerun. */
export async function getResearchReport(threadId: string): Promise<ReportResponse> {
  const response = await fetch(`${API_BASE_URL}/research/${threadId}/report`);
  if (!response.ok) {
    throw new Error(`/research/${threadId}/report failed with status ${response.status}`);
  }
  return (await response.json()) as ReportResponse;
}
