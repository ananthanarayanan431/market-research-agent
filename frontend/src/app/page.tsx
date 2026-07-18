"use client";

import { useEffect, useState } from "react";
import { Sidebar } from "@/components/app/sidebar";
import { ChatPanel } from "@/components/app/chat-panel";
import { DrawerMode, ResearchDrawer } from "@/components/app/research-drawer";
import { PROGRESS_STEPS } from "@/lib/mock-data";
import { Message, Phase } from "@/lib/types";

export default function Home() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [topic, setTopic] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMode, setDrawerMode] = useState<DrawerMode>("progress");
  const [messages, setMessages] = useState<Message[]>([]);

  const addMessage = (m: Message) =>
    setMessages((prev) => [...prev, m]);

  useEffect(() => {
    if (phase !== "running") return;

    const timer = setTimeout(() => {
      if (stepIndex >= PROGRESS_STEPS.length - 1) {
        setPhase("complete");
        addMessage({
          id: crypto.randomUUID(),
          kind: "assistant",
          text: "Research complete — 24 sources reviewed with high confidence. How would you like the findings delivered?",
        });
      } else {
        setStepIndex(stepIndex + 1);
      }
    }, 1100);
    return () => clearTimeout(timer);
  }, [phase, stepIndex]);

  const startRun = () => {
    setStepIndex(0);
    setPhase("running");
    setDrawerMode("progress");
    setDrawerOpen(true);
  };

  const resetAll = () => {
    setPhase("idle");
    setTopic(null);
    setStepIndex(0);
    setMessages([]);
    setDrawerOpen(false);
    setDrawerMode("progress");
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <Sidebar onNewResearch={resetAll} />
      <div className="flex min-w-0 flex-1">
        <ChatPanel
          phase={phase}
          setPhase={setPhase}
          topic={topic}
          setTopic={setTopic}
          stepIndex={stepIndex}
          messages={messages}
          addMessage={addMessage}
          onStartRun={startRun}
          onOpenDrawer={() => {
            setDrawerMode("progress");
            setDrawerOpen(true);
          }}
          onChooseFormat={(format) => {
            setDrawerMode(format === "paragraph" ? "report" : "table");
            setDrawerOpen(true);
          }}
        />
        {drawerOpen && topic && (
          <div className="hidden w-[420px] shrink-0 md:block">
            <ResearchDrawer
              title={topic}
              mode={drawerMode}
              stepIndex={stepIndex}
              onClose={() => setDrawerOpen(false)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
