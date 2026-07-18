"use client";

import { useEffect, useState } from "react";
import { BarChart3, Plus, Sun, Moon } from "lucide-react";
import { listSessions } from "@/lib/api";
import { SessionSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

function timeAgo(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function Sidebar({
  onNewResearch,
  onSelectSession,
  refreshKey,
}: {
  onNewResearch: () => void;
  onSelectSession: (session: SessionSummary) => void;
  refreshKey: number;
}) {
  const [light, setLight] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    listSessions()
      .then((result) => {
        if (!cancelled) setSessions(result);
      })
      .catch(() => {
        if (!cancelled) setSessions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const toggleTheme = () => {
    setLight((prev) => {
      const next = !prev;
      document.documentElement.classList.toggle("dark", !next);
      return next;
    });
  };

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
      <div className="flex items-center gap-2 px-4 pt-5 pb-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500 text-white">
          <BarChart3 className="h-5 w-5" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold">Market Research Agent</div>
          <div className="text-[10px] tracking-wide text-muted-foreground">
            AGENTDROPS
          </div>
        </div>
      </div>

      <div className="px-4 pb-2">
        <button
          onClick={onNewResearch}
          className="flex w-full items-center justify-center gap-2 rounded-md border bg-background/40 py-2 text-sm font-medium hover:bg-accent"
        >
          <Plus className="h-4 w-4" />
          New research
        </button>
      </div>

      <div className="mt-2 flex-1 overflow-y-auto px-4">
        <div className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground">
          RECENT
        </div>
        <ul className="space-y-3">
          {sessions.map((s) => (
            <li
              key={s.id}
              onClick={() => onSelectSession(s)}
              className="cursor-pointer text-sm hover:text-foreground"
            >
              <div className="truncate text-foreground/90">{s.title}</div>
              <div className="text-xs text-muted-foreground">
                {timeAgo(s.created_at)}
                {s.status !== "done" && ` · ${s.status}`}
              </div>
            </li>
          ))}
          {sessions.length === 0 && (
            <li className="text-xs text-muted-foreground">No research yet.</li>
          )}
        </ul>
      </div>

      <div className="space-y-2 border-t px-4 py-4">
        <button
          onClick={toggleTheme}
          className={cn(
            "flex w-full items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-accent"
          )}
        >
          {light ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
          {light ? "Dark mode" : "Light mode"}
        </button>
        <div className="text-[11px] text-muted-foreground">
          Deep research · paragraph &amp; tabular output
        </div>
      </div>
    </aside>
  );
}
