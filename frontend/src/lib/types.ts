export type Phase = "idle" | "clarifying" | "running" | "complete" | "delivered";

export type Message =
  | { id: string; kind: "user"; text: string }
  | { id: string; kind: "assistant"; text: string };

export type ProgressStep = {
  title: string;
  detail?: string;
};

export type ResearchSource = {
  topic: string;
  summary: string;
};

export type StreamEvent =
  | { type: "progress"; step: string; detail?: string }
  | { type: "source"; topic: string; summary: string }
  | { type: "clarify"; thread_id: string; response: string }
  | { type: "done"; thread_id: string; report: string };

export type ResearchStatusValue = "clarifying" | "running" | "done";

export type SessionSummary = {
  id: string;
  title: string;
  created_at: string;
  status: ResearchStatusValue;
};

export type ResearchStatus = {
  thread_id: string;
  status: ResearchStatusValue;
  research_brief: string | null;
  report: string | null;
};

export type ReportResponse = {
  thread_id: string;
  report: string;
  sources: ResearchSource[];
};
