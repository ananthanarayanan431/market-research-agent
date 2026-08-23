"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, CheckCircle2, Database, FileText, Loader2, Sparkles } from "lucide-react";
import { Message, Phase, StreamEvent } from "@/lib/types";
import { DrawerMode } from "@/components/app/research-drawer";
import { cn } from "@/lib/utils";

export const FALLBACK_STARTER_SUGGESTIONS = [
  "Competitive landscape for digital banking platforms in the US",
  "Market sizing for embedded finance and BNPL in Southeast Asia",
  "Investment trends in AI-driven wealth management platforms",
];

export function ChatPanel({
  phase,
  setPhase,
  topic,
  setTopic,
  messages,
  addMessage,
  sendMessage,
  onStartRun,
  onOpenDrawer,
  drawerOpen,
  clarifySuggestions,
  setClarifySuggestions,
  starterSuggestions,
  useContextHub,
  setUseContextHub,
}: {
  phase: Phase;
  setPhase: (p: Phase) => void;
  topic: string | null;
  setTopic: (t: string) => void;
  messages: Message[];
  addMessage: (m: Message) => void;
  sendMessage: (text: string) => Promise<StreamEvent | null>;
  onStartRun: () => void;
  onOpenDrawer: (mode?: DrawerMode) => void;
  drawerOpen: boolean;
  clarifySuggestions: string[];
  setClarifySuggestions: (s: string[]) => void;
  starterSuggestions: string[];
  useContextHub: boolean;
  setUseContextHub: (v: boolean) => void;
}) {
  const [input, setInput] = useState("");
  const [chipAnswer, setChipAnswer] = useState("");
  const [selectedChips, setSelectedChips] = useState<string[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, phase]);

  /** Apply a settled `clarify | done | error` stream event to messages/suggestions/phase.
   * Shared by `startTopic` and `submitClarify`, which only differ in which phase to fall back
   * to on `clarify`/`error` (the former is already "clarifying"; the latter returns to it). */
  const applyTerminalEvent = (
    event: StreamEvent,
    { clarifyPhase, errorPhase }: { clarifyPhase: Phase; errorPhase: Phase }
  ) => {
    if (event.type === "clarify") {
      addMessage({ id: crypto.randomUUID(), kind: "assistant", text: event.response });
      setClarifySuggestions(event.suggestions);
      setPhase(clarifyPhase);
    } else if (event.type === "done") {
      setClarifySuggestions([]);
      addMessage({
        id: crypto.randomUUID(),
        kind: "assistant",
        text: "Research complete — I've opened the full report in the panel on the right.",
      });
      setPhase("complete");
      onOpenDrawer("report");
    } else if (event.type === "error") {
      setClarifySuggestions([]);
      addMessage({ id: crypto.randomUUID(), kind: "assistant", text: `Research failed: ${event.message}` });
      setPhase(errorPhase);
    }
  };

  const startTopic = async (text: string) => {
    if (!text.trim()) return;
    setTopic(text);
    addMessage({ id: crypto.randomUUID(), kind: "user", text });
    setInput("");
    // Optimistically treat this like a run in progress — opens the drawer and starts
    // showing live steps immediately. If the model comes back asking to clarify instead,
    // applyTerminalEvent's "clarify" branch below flips the phase back. Without this, the
    // screen would sit blank for the full clarify_with_user call — and, whenever no
    // clarification turns out to be needed, for the entire research run that follows it in
    // that same request, since that whole pipeline runs inside one /chat/stream call.
    onStartRun();
    try {
      const event = await sendMessage(text);
      // null means the sidebar switched to a different session before this stream settled —
      // drop the result instead of appending it to whatever session is now on screen.
      if (!event) return;
      applyTerminalEvent(event, { clarifyPhase: "clarifying", errorPhase: "idle" });
    } catch {
      addMessage({
        id: crypto.randomUUID(),
        kind: "assistant",
        text: "Couldn't reach the research agent — please try again.",
      });
      setPhase("idle");
    }
  };

  const toggleChip = (chip: string) => {
    setSelectedChips((prev) => {
      const next = prev.includes(chip)
        ? prev.filter((c) => c !== chip)
        : [...prev, chip];
      setChipAnswer(next.join("; "));
      return next;
    });
  };

  const submitClarify = async () => {
    const text = chipAnswer.trim() || "Go ahead and start.";
    addMessage({ id: crypto.randomUUID(), kind: "user", text });
    setChipAnswer("");
    setSelectedChips([]);
    onStartRun();
    try {
      const event = await sendMessage(text);
      if (!event) return;
      applyTerminalEvent(event, { clarifyPhase: "clarifying", errorPhase: "clarifying" });
    } catch {
      addMessage({
        id: crypto.randomUUID(),
        kind: "assistant",
        text: "Something went wrong during research — please try again.",
      });
      setPhase("clarifying");
    }
  };

  return (
    <div className="flex h-full flex-1 flex-col">
      <div className="flex items-center justify-between border-b px-6 py-3 text-xs text-muted-foreground">
        <div className="flex items-center">
          Market Research Agent Application
          <span className="ml-2 rounded bg-muted px-2 py-0.5 text-[10px]">
            Content is user-generated and unverified.
          </span>
        </div>
        {phase === "complete" && topic && !drawerOpen && (
          <button
            onClick={() => onOpenDrawer("report")}
            className="flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-accent"
          >
            <FileText className="h-3.5 w-3.5" />
            View report
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-8">
        {phase === "idle" && messages.length === 0 ? (
          <div className="mx-auto flex max-w-2xl flex-col items-center gap-6 pt-16 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-500/10">
              <Sparkles className="h-6 w-6 text-blue-500" />
            </div>
            <h1 className="text-3xl font-semibold tracking-tight">
              What market should we dig into?
            </h1>
            <p className="text-muted-foreground">
              Give me an objective. I&apos;ll ask a few sharpening questions,
              run deep research across the market, and hand you back a
              markdown report you can download as a PDF.
            </p>
            <div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-3">
              {starterSuggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => startTopic(s)}
                  className="rounded-lg border p-4 text-left text-sm transition-colors hover:border-blue-500/40 hover:bg-accent"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-2xl flex-col gap-4">
            {messages.map((m) =>
              m.kind === "user" ? (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[80%] rounded-xl bg-blue-500 px-4 py-2 text-sm text-white shadow-sm">
                    {m.text}
                  </div>
                </div>
              ) : (
                <div key={m.id} className="max-w-[85%] text-sm leading-relaxed">
                  {m.text}
                </div>
              )
            )}

            {(phase === "running" || phase === "complete") && topic && (
              <button
                onClick={() => onOpenDrawer(phase === "running" ? "progress" : "report")}
                className="flex items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors hover:bg-accent"
              >
                {phase === "running" ? (
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-blue-500" />
                ) : (
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
                )}
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{topic}</div>
                  <div className="text-xs text-muted-foreground">
                    {phase === "running" ? "Researching..." : "Research complete"}
                  </div>
                </div>
              </button>
            )}

            {phase === "clarifying" && clarifySuggestions.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {clarifySuggestions.map((chip) => (
                  <button
                    key={chip}
                    onClick={() => toggleChip(chip)}
                    className={cn(
                      "rounded-full border px-3 py-1.5 text-xs transition-colors",
                      selectedChips.includes(chip)
                        ? "border-blue-500 bg-blue-500/10 text-blue-500"
                        : "hover:bg-accent"
                    )}
                  >
                    {chip}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="border-t px-6 py-4">
        <div className="mx-auto max-w-2xl rounded-xl border p-3 transition-colors focus-within:border-blue-500/40">
          <textarea
            value={phase === "clarifying" ? chipAnswer : input}
            onChange={(e) =>
              phase === "clarifying"
                ? setChipAnswer(e.target.value)
                : setInput(e.target.value)
            }
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (phase === "clarifying") submitClarify();
                else if (phase === "idle") startTopic(input);
              }
            }}
            placeholder={
              phase === "running"
                ? "Researching — hang tight..."
                : phase === "clarifying"
                ? "Add region, timeframe, focus..."
                : "What do you want to research?"
            }
            disabled={phase === "running" || phase === "complete"}
            rows={1}
            className="w-full resize-none bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
          />
          <div className="mt-2 flex items-center justify-between">
            <span className="flex items-center gap-1.5 rounded-full bg-blue-500/10 px-2.5 py-1 text-xs font-medium text-blue-500">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
              Deep Research
            </span>
            <button
              type="button"
              onClick={() => setUseContextHub(!useContextHub)}
              title="Include your uploaded Context Hub knowledge in this research"
              className={cn(
                "ml-2 flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors",
                useContextHub
                  ? "border-blue-500 bg-blue-500/10 text-blue-500"
                  : "text-muted-foreground hover:bg-accent"
              )}
            >
              <Database className="h-3 w-3" />
              Use uploaded knowledge
            </button>
            <button
              onClick={() => {
                if (phase === "idle") startTopic(input);
                else if (phase === "clarifying") submitClarify();
              }}
              disabled={phase === "running" || phase === "complete"}
              className={cn(
                "flex h-8 w-8 items-center justify-center rounded-full transition-colors",
                phase === "clarifying" || (phase === "idle" && input.trim())
                  ? "bg-blue-500 text-white hover:bg-blue-600"
                  : "bg-muted text-muted-foreground"
              )}
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
