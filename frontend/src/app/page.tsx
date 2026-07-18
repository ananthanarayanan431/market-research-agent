"use client";

import { useEffect, useRef, useState } from "react";
import { Sidebar } from "@/components/app/sidebar";
import { ChatPanel, Phase } from "@/components/app/chat-panel";
import { DrawerMode, ResearchDrawer } from "@/components/app/research-drawer";
import { PROGRESS_STEPS } from "@/lib/mock-data";

export default function Home() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [topic, setTopic] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMode, setDrawerMode] = useState<DrawerMode>("progress");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [prevPhase, setPrevPhase] = useState<Phase>(phase);

  if (prevPhase !== phase) {
    setPrevPhase(phase);
    if (phase === "running" && stepIndex !== 0) {
      setStepIndex(0);
    }
  }

  useEffect(() => {
    if (phase !== "running") return;
    timerRef.current = setInterval(() => {
      setStepIndex((prev) => {
        if (prev >= PROGRESS_STEPS.length - 1) {
          if (timerRef.current) clearInterval(timerRef.current);
          setPhase("complete");
          return prev;
        }
        return prev + 1;
      });
    }, 1100);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [phase]);

  const resetAll = () => {
    setPhase("idle");
    setTopic(null);
    setStepIndex(0);
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
