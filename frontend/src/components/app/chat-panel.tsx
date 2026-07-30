"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, CheckCircle2, Loader2, Sparkles } from "lucide-react";
import { SUGGESTIONS } from "@/lib/mock-data";
import { Message, Phase, StreamEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

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
  onChooseFormat,
  clarifySuggestions,
  setClarifySuggestions,
}: {
  phase: Phase;
  setPhase: (p: Phase) => void;
  topic: string | null;
  setTopic: (t: string) => void;
  messages: Message[];
  addMessage: (m: Message) => void;
  sendMessage: (text: string) => Promise<StreamEvent | null>;
  onStartRun: () => void;
  onOpenDrawer: () => void;
  onChooseFormat: (format: "paragraph" | "table") => void;
  clarifySuggestions: string[];
  setClarifySuggestions: (s: string[]) => void;
}) {
  const [input, setInput] = useState("");
  const [chipAnswer, setChipAnswer] = useState("");
  const [selectedChips, setSelectedChips] = useState<string[]>([]);
  const [deliveryChosen, setDeliveryChosen] = useState<
    "paragraph" | "table" | null
  >(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, phase]);

  // `deliveryChosen` is scoped to one research run: reset it whenever the active topic changes
  // (a new topic, or a different session reopened from the sidebar), otherwise the format
  // buttons stay hidden on every run after the first. Reset during render (not an effect) per
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const [prevTopic, setPrevTopic] = useState(topic);
  if (topic !== prevTopic) {
    setPrevTopic(topic);
    setDeliveryChosen(null);
  }

  const startTopic = async (text: string) => {
    if (!text.trim()) return;
    setTopic(text);
    addMessage({ id: crypto.randomUUID(), kind: "user", text });
    setInput("");
    setPhase("clarifying");
    try {
      const event = await sendMessage(text);
      // null means the sidebar switched to a different session before this stream settled —
      // drop the result instead of appending it to whatever session is now on screen.
      if (!event) return;
      if (event.type === "clarify") {
        addMessage({ id: crypto.randomUUID(), kind: "assistant", text: event.response });
        setClarifySuggestions(event.suggestions);
      } else if (event.type === "done") {
        setClarifySuggestions([]);
        addMessage({
          id: crypto.randomUUID(),
          kind: "assistant",
          text: "Research complete. How would you like the findings delivered?",
        });
        setPhase("complete");
      } else if (event.type === "error") {
        setClarifySuggestions([]);
        addMessage({ id: crypto.randomUUID(), kind: "assistant", text: `Research failed: ${event.message}` });
        setPhase("idle");
      }
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
      if (event.type === "clarify") {
        addMessage({ id: crypto.randomUUID(), kind: "assistant", text: event.response });
        setClarifySuggestions(event.suggestions);
        setPhase("clarifying");
      } else if (event.type === "done") {
        setClarifySuggestions([]);
        addMessage({
          id: crypto.randomUUID(),
          kind: "assistant",
          text: "Research complete. How would you like the findings delivered?",
        });
        setPhase("complete");
      } else if (event.type === "error") {
        addMessage({ id: crypto.randomUUID(), kind: "assistant", text: `Research failed: ${event.message}` });
        setPhase("clarifying");
      }
    } catch {
      addMessage({
        id: crypto.randomUUID(),
        kind: "assistant",
        text: "Something went wrong during research — please try again.",
      });
      setPhase("clarifying");
    }
  };

  const chooseFormat = (format: "paragraph" | "table") => {
    setDeliveryChosen(format);
    addMessage({
      id: crypto.randomUUID(),
      kind: "user",
      text: format === "paragraph" ? "Paragraph report, please." : "Excel / table, please.",
    });
    onChooseFormat(format);
    setPhase("delivered");
    setTimeout(() => {
      addMessage({
        id: crypto.randomUUID(),
        kind: "assistant",
        text: "Done — I've opened the full report in the panel on the right.",
      });
    }, 400);
  };

  return (
    <div className="flex h-full flex-1 flex-col">
      <div className="flex items-center border-b px-6 py-3 text-xs text-muted-foreground">
        Market Research Agent Application
        <span className="ml-2 rounded bg-muted px-2 py-0.5 text-[10px]">
          Content is user-generated and unverified.
        </span>
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
              run deep research across the market, and hand you back a report
              or a data table.
            </p>
            <div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-3">
              {SUGGESTIONS.map((s) => (
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

            {(phase === "running" || phase === "complete" || phase === "delivered") &&
              topic && (
                <button
                  onClick={onOpenDrawer}
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

            {phase === "complete" && deliveryChosen === null && (
              <div className="flex gap-2">
                <button
                  onClick={() => chooseFormat("paragraph")}
                  className="rounded-md bg-blue-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-600"
                >
                  Paragraph report
                </button>
                <button
                  onClick={() => chooseFormat("table")}
                  className="rounded-md border px-4 py-2 text-sm font-medium transition-colors hover:bg-accent"
                >
                  Excel / table
                </button>
              </div>
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
            disabled={phase === "running" || phase === "complete" || phase === "delivered"}
            rows={1}
            className="w-full resize-none bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
          />
          <div className="mt-2 flex items-center justify-between">
            <span className="flex items-center gap-1.5 rounded-full bg-blue-500/10 px-2.5 py-1 text-xs font-medium text-blue-500">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
              Deep Research
            </span>
            <button
              onClick={() => {
                if (phase === "idle") startTopic(input);
                else if (phase === "clarifying") submitClarify();
              }}
              disabled={phase === "running" || phase === "complete" || phase === "delivered"}
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
