"use client";

import { useState } from "react";
import { Sidebar } from "@/components/app/sidebar";
import { ChatPanel } from "@/components/app/chat-panel";
import { DrawerMode, ResearchDrawer } from "@/components/app/research-drawer";
import { getResearchReport, getResearchStatus, streamChat } from "@/lib/api";
import {
  Message,
  Phase,
  ProgressStep,
  ResearchSource,
  SessionSummary,
  StreamEvent,
} from "@/lib/types";

export default function Home() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [topic, setTopic] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [steps, setSteps] = useState<ProgressStep[]>([]);
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [report, setReport] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMode, setDrawerMode] = useState<DrawerMode>("progress");
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionsRefresh, setSessionsRefresh] = useState(0);

  const addMessage = (m: Message) => setMessages((prev) => [...prev, m]);

  /** Send one chat turn to /chat/stream, folding progress/source events into state as they
   * arrive, and returning the terminal (clarify | done) event once the stream ends. */
  const sendMessage = async (text: string): Promise<StreamEvent> => {
    let terminal: StreamEvent | null = null;
    await streamChat(text, threadId, (event) => {
      if (event.type === "progress") {
        setSteps((prev) => [...prev, { title: event.step, detail: event.detail }]);
      } else if (event.type === "source") {
        setSources((prev) => [...prev, { topic: event.topic, summary: event.summary }]);
      } else {
        setThreadId(event.thread_id);
        if (event.type === "done") setReport(event.report);
        terminal = event;
      }
    });
    if (!terminal) throw new Error("/chat/stream ended without a clarify or done event");
    setSessionsRefresh((prev) => prev + 1);
    return terminal;
  };

  /** Reopen a past session from the sidebar: fetch its report if done, else its live status. */
  const selectSession = async (session: SessionSummary) => {
    setTopic(session.title);
    setThreadId(session.id);
    setMessages([]);
    setSteps([]);
    setSources([]);
    setReport(null);
    setDrawerOpen(true);

    if (session.status === "done") {
      try {
        const { report: fetchedReport, sources: fetchedSources } = await getResearchReport(
          session.id
        );
        setReport(fetchedReport);
        setSources(fetchedSources);
        setDrawerMode("report");
        setPhase("complete");
      } catch {
        setPhase("idle");
      }
      return;
    }

    try {
      const status = await getResearchStatus(session.id);
      setDrawerMode("progress");
      setPhase(status.status === "clarifying" ? "clarifying" : "running");
    } catch {
      setPhase("idle");
    }
  };

  const startRun = () => {
    setSteps([]);
    setSources([]);
    setReport(null);
    setPhase("running");
    setDrawerMode("progress");
    setDrawerOpen(true);
  };

  const resetAll = () => {
    setPhase("idle");
    setTopic(null);
    setThreadId(null);
    setSteps([]);
    setSources([]);
    setReport(null);
    setMessages([]);
    setDrawerOpen(false);
    setDrawerMode("progress");
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <Sidebar
        onNewResearch={resetAll}
        onSelectSession={selectSession}
        refreshKey={sessionsRefresh}
      />
      <div className="flex min-w-0 flex-1">
        <ChatPanel
          phase={phase}
          setPhase={setPhase}
          topic={topic}
          setTopic={setTopic}
          messages={messages}
          addMessage={addMessage}
          sendMessage={sendMessage}
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
              steps={steps}
              sources={sources}
              report={report}
              isRunning={phase === "running"}
              onClose={() => setDrawerOpen(false)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
