export type Phase = "idle" | "clarifying" | "running" | "complete" | "delivered";

export type Message =
  | { id: string; kind: "user"; text: string }
  | { id: string; kind: "assistant"; text: string };
