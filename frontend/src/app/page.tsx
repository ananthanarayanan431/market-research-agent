"use client";

import { useEffect, useRef, useState } from "react";
import { Sidebar } from "@/components/app/sidebar";
import { ChatPanel, FALLBACK_STARTER_SUGGESTIONS } from "@/components/app/chat-panel";
import { DrawerMode, ResearchDrawer } from "@/components/app/research-drawer";
import { getResearchReport, getResearchStatus, getStarterSuggestions, streamChat } from "@/lib/api";
import { withSpan } from "@/lib/telemetry";
import {
  Message,
  Phase,
  ProgressStep,
  ResearchSource,
  ResearchStatus,
  SessionSummary,
  StreamEvent,
} from "@/lib/types";

export default function Home() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [topic, setTopic] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [steps, setSteps] = useState<ProgressStep[]>([]);
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [clarifySuggestions, setClarifySuggestions] = useState<string[]>([]);
  const [report, setReport] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerExpanded, setDrawerExpanded] = useState(false);
  const [drawerMode, setDrawerMode] = useState<DrawerMode>("progress");
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionsRefresh, setSessionsRefresh] = useState(0);
  const [starterSuggestions, setStarterSuggestions] = useState<string[]>(
    FALLBACK_STARTER_SUGGESTIONS
  );

  // Bumped on every selectSession call; async work below checks it's still current before
  // applying results, so a slower session-A fetch can't clobber a faster session-B selection.
  const selectionTokenRef = useRef(0);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Tracks the clarify_question text already appended to `messages` for the current
  // session/poll cycle, so pollUntilSettled's 3s tick doesn't re-append the same question
  // every time it observes "clarifying" — only a genuinely new question gets a new message.
  const lastClarifyQuestionRef = useRef<string | null>(null);

  const addMessage = (m: Message) => setMessages((prev) => [...prev, m]);

  useEffect(() => {
    let cancelled = false;
    getStarterSuggestions()
      .then((prompts) => {
        if (!cancelled && prompts.length > 0) setStarterSuggestions(prompts);
      })
      .catch(() => {
        // Keep the fallback list — the idle screen must never show nothing.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** Apply a fetched `ResearchStatus`'s clarify fields to state: refreshes the suggestion chips,
   * and — only when `clarify_question` is genuinely new — appends (or, for a freshly opened
   * session, seeds) an assistant message for it. Shared by `pollUntilSettled` (which appends to
   * the running conversation) and `selectSession` (which seeds a just-cleared one). */
  const applyClarifyStatus = (status: ResearchStatus, seedMessages: boolean) => {
    if (status.status !== "clarifying") {
      setClarifySuggestions([]);
      return;
    }
    setClarifySuggestions(status.clarify_suggestions);
    if (status.clarify_question && status.clarify_question !== lastClarifyQuestionRef.current) {
      lastClarifyQuestionRef.current = status.clarify_question;
      const message: Message = { id: crypto.randomUUID(), kind: "assistant", text: status.clarify_question };
      if (seedMessages) setMessages([message]);
      else addMessage(message);
    }
  };

  /** Send one chat turn to /chat/stream, folding progress/source events into state as they
   * arrive, and returning the terminal (clarify | done) event once the stream ends — or `null`
   * if the sidebar switched to a different session before the stream finished, telling the
   * caller to drop the result rather than append it to whatever session is now on screen. */
  const sendMessage = async (text: string): Promise<StreamEvent | null> =>
    withSpan(
      "research.submit",
      { "research.is_followup": threadId !== null },
      async (span) => {
        // Captured once up front: if the sidebar switches to a different session while this
        // stream is still delivering events, selectionTokenRef.current moves on and these
        // callbacks stop touching state — otherwise a backgrounded run's progress/source
        // events keep landing on whatever session the user has since switched to.
        const token = selectionTokenRef.current;
        let terminal: StreamEvent | null = null;
        let sourceCount = 0;
        await streamChat(text, threadId, (event) => {
          if (selectionTokenRef.current !== token) return;
          if (event.type === "progress") {
            // A new top-level stage retires every earlier top-level step, but leaves concurrent
            // per-topic research steps running — those close individually on their own "source"
            // event below, since several can still be in flight when the next stage starts.
            setSteps((prev) => [
              ...prev.map((s) => (s.topic ? s : { ...s, active: false })),
              { title: event.step, detail: event.detail, topic: event.topic, active: true },
            ]);
          } else if (event.type === "source") {
            sourceCount += 1;
            setSources((prev) => [...prev, { topic: event.topic, summary: event.summary }]);
            setSteps((prev) =>
              prev.map((s) => (s.topic === event.topic ? { ...s, active: false } : s))
            );
          } else if (event.type === "source_url") {
            // Surface the page currently being read as the active topic step's live detail line.
            setSteps((prev) =>
              prev.map((s) =>
                s.topic === event.topic && s.active
                  ? { ...s, detail: `Reading: ${event.title}` }
                  : s
              )
            );
          } else {
            setThreadId(event.thread_id);
            if (event.type === "done") setReport(event.report);
            terminal = event;
          }
        });
        if (!terminal) throw new Error("/chat/stream ended without a clarify or done event");
        // `terminal` is narrowed to never by the closure assignment above; TS can't see that
        // the callback ran, so re-widen before reading its fields.
        const settled = terminal as StreamEvent;
        span.setAttribute("research.outcome", settled.type);
        span.setAttribute("research.sources", sourceCount);
        setSessionsRefresh((prev) => prev + 1);
        return selectionTokenRef.current === token ? settled : null;
      }
    );

  /** Poll a reopened session's status every 3s until it leaves running/clarifying, then load
   * its report. Stops itself once `token` no longer matches the active selection. */
  const pollUntilSettled = (sessionId: string, token: number) => {
    if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
    pollTimeoutRef.current = setTimeout(async () => {
      if (selectionTokenRef.current !== token) return;
      try {
        const status = await getResearchStatus(sessionId);
        if (selectionTokenRef.current !== token) return;

        if (status.status === "done") {
          const { report: fetchedReport, sources: fetchedSources } =
            await getResearchReport(sessionId);
          if (selectionTokenRef.current !== token) return;
          setReport(fetchedReport);
          setSources(fetchedSources);
          setDrawerMode("report");
          setPhase("complete");
          return;
        }
        if (status.status === "failed") {
          setPhase("idle");
          return;
        }
        applyClarifyStatus(status, false);
        setPhase(status.status === "clarifying" ? "clarifying" : "running");
        pollUntilSettled(sessionId, token);
      } catch {
        if (selectionTokenRef.current === token) setPhase("idle");
      }
    }, 3000);
  };

  /** Reopen a past session from the sidebar: fetch its report if done, else its live status,
   * polling until it settles if the run is still in flight. */
  const selectSession = async (session: SessionSummary) => {
    const token = ++selectionTokenRef.current;
    if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);

    setTopic(session.title);
    setThreadId(session.id);
    setMessages([]);
    setSteps([]);
    setSources([]);
    setClarifySuggestions([]);
    setReport(null);
    setDrawerOpen(true);
    setDrawerExpanded(false);
    lastClarifyQuestionRef.current = null;

    if (session.status === "done") {
      try {
        const { report: fetchedReport, sources: fetchedSources } = await getResearchReport(
          session.id
        );
        if (selectionTokenRef.current !== token) return;
        setReport(fetchedReport);
        setSources(fetchedSources);
        setDrawerMode("report");
        setPhase("complete");
      } catch {
        if (selectionTokenRef.current === token) setPhase("idle");
      }
      return;
    }

    try {
      const status = await getResearchStatus(session.id);
      if (selectionTokenRef.current !== token) return;
      setDrawerMode("progress");
      applyClarifyStatus(status, true);
      setPhase(status.status === "clarifying" ? "clarifying" : "running");
      if (
        status.status === "clarifying" ||
        status.status === "running" ||
        status.status === "queued"
      ) {
        pollUntilSettled(session.id, token);
      }
    } catch {
      if (selectionTokenRef.current === token) setPhase("idle");
    }
  };

  const startRun = () => {
    selectionTokenRef.current += 1;
    if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
    setSteps([]);
    setSources([]);
    setClarifySuggestions([]);
    setReport(null);
    setPhase("running");
    setDrawerMode("progress");
    setDrawerOpen(true);
    setDrawerExpanded(false);
    lastClarifyQuestionRef.current = null;
  };

  const resetAll = () => {
    selectionTokenRef.current += 1;
    if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
    setPhase("idle");
    setTopic(null);
    setThreadId(null);
    setSteps([]);
    setSources([]);
    setClarifySuggestions([]);
    setReport(null);
    setMessages([]);
    setDrawerOpen(false);
    setDrawerExpanded(false);
    setDrawerMode("progress");
    lastClarifyQuestionRef.current = null;
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <Sidebar
        onNewResearch={resetAll}
        onSelectSession={selectSession}
        onSessionDeleted={(id) => {
          if (id === threadId) resetAll();
        }}
        refreshKey={sessionsRefresh}
        activeSessionId={threadId}
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
          onOpenDrawer={(mode) => {
            setDrawerMode(mode ?? "progress");
            setDrawerOpen(true);
          }}
          drawerOpen={drawerOpen}
          clarifySuggestions={clarifySuggestions}
          setClarifySuggestions={setClarifySuggestions}
          starterSuggestions={starterSuggestions}
        />
        {drawerOpen && topic && (
          <div
            className={
              drawerExpanded
                ? "fixed inset-0 z-50 hidden md:block"
                : "hidden w-[46%] min-w-[460px] max-w-[860px] shrink-0 md:block"
            }
          >
            <ResearchDrawer
              title={topic}
              mode={drawerMode}
              steps={steps}
              sources={sources}
              report={report}
              isRunning={phase === "running" || phase === "clarifying"}
              expanded={drawerExpanded}
              onToggleExpand={() => setDrawerExpanded((v) => !v)}
              onClose={() => {
                setDrawerOpen(false);
                setDrawerExpanded(false);
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
