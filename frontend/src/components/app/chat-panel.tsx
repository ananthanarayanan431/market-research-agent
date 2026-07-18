"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, CheckCircle2, Loader2 } from "lucide-react";
import { CLARIFY_CHIPS, PROGRESS_STEPS, SUGGESTIONS } from "@/lib/mock-data";
import { Message, Phase } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ChatPanel({
  phase,
  setPhase,
  topic,
  setTopic,
  stepIndex,
  messages,
  addMessage,
  onStartRun,
  onOpenDrawer,
  onChooseFormat,
}: {
  phase: Phase;
  setPhase: (p: Phase) => void;
  topic: string | null;
  setTopic: (t: string) => void;
  stepIndex: number;
  messages: Message[];
  addMessage: (m: Message) => void;
  onStartRun: () => void;
  onOpenDrawer: () => void;
  onChooseFormat: (format: "paragraph" | "table") => void;
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
  }, [messages, phase, stepIndex]);

  const startTopic = (text: string) => {
    if (!text.trim()) return;
    setTopic(text);
    addMessage({ id: crypto.randomUUID(), kind: "user", text });
    addMessage({
      id: crypto.randomUUID(),
      kind: "assistant",
      text: "Got it. Before I dive in — what region should I focus on, what's the timeframe, and are you more interested in competitors, pricing, or customer demand? Add whatever's relevant below and send, or just hit start.",
    });
    setPhase("clarifying");
    setInput("");
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

  const submitClarify = () => {
    const text = chipAnswer.trim() || "Go ahead and start.";
    addMessage({ id: crypto.randomUUID(), kind: "user", text });
    setChipAnswer("");
    setSelectedChips([]);
    onStartRun();
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
            <h1 className="text-3xl font-semibold">
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
                  className="rounded-lg border p-4 text-left text-sm hover:bg-accent"
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
                  <div className="max-w-[80%] rounded-xl bg-blue-500 px-4 py-2 text-sm text-white">
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
                  className="flex items-center gap-3 rounded-lg border px-4 py-3 text-left hover:bg-accent"
                >
                  {phase === "running" ? (
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-blue-500" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
                  )}
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{topic}</div>
                    <div className="text-xs text-muted-foreground">
                      {phase === "running"
                        ? `${PROGRESS_STEPS[Math.min(stepIndex, PROGRESS_STEPS.length - 1)].title}...`
                        : "Research complete"}
                    </div>
                  </div>
                </button>
              )}

            {phase === "complete" && deliveryChosen === null && (
              <div className="flex gap-2">
                <button
                  onClick={() => chooseFormat("paragraph")}
                  className="rounded-md border px-4 py-2 text-sm font-medium text-blue-500 hover:bg-accent"
                >
                  Paragraph report
                </button>
                <button
                  onClick={() => chooseFormat("table")}
                  className="rounded-md border px-4 py-2 text-sm font-medium text-blue-500 hover:bg-accent"
                >
                  Excel / table
                </button>
              </div>
            )}

            {phase === "clarifying" && (
              <div className="flex flex-wrap gap-2">
                {CLARIFY_CHIPS.map((chip) => (
                  <button
                    key={chip}
                    onClick={() => toggleChip(chip)}
                    className={cn(
                      "rounded-full border px-3 py-1.5 text-xs",
                      selectedChips.includes(chip)
                        ? "border-blue-500 text-blue-500"
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
        <div className="mx-auto max-w-2xl rounded-xl border p-3">
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
                "flex h-8 w-8 items-center justify-center rounded-full",
                phase === "clarifying" || (phase === "idle" && input.trim())
                  ? "bg-blue-500 text-white"
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
