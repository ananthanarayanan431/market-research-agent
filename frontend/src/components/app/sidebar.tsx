"use client";

import { useState } from "react";
import { BarChart3, Plus, Sun, Moon } from "lucide-react";
import { RECENT_SESSIONS } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

export function Sidebar({ onNewResearch }: { onNewResearch: () => void }) {
  const [light, setLight] = useState(false);

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
          {RECENT_SESSIONS.map((s) => (
            <li
              key={s.id}
              className="cursor-pointer text-sm hover:text-foreground"
            >
              <div className="truncate text-foreground/90">{s.title}</div>
              <div className="text-xs text-muted-foreground">{s.timeAgo}</div>
            </li>
          ))}
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
