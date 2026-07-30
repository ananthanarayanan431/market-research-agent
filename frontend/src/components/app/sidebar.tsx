"use client";

import { useEffect, useState } from "react";
import {
  BarChart3,
  Check,
  Loader2,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Sun,
  Moon,
  Trash2,
  X,
} from "lucide-react";
import {
  deleteSession,
  listSessions,
  renameSession,
  SessionInProgressError,
  setSessionPinned,
} from "@/lib/api";
import { SessionSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEARCH_DEBOUNCE_MS = 300;

function timeAgo(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

type Group = { label: string; items: SessionSummary[] };

/** Buckets non-pinned sessions by recency (Today / Yesterday / Previous 7 Days / Older);
 * pinned sessions always form their own group at the top regardless of age. */
function groupSessions(sessions: SessionSummary[]): Group[] {
  const pinned = sessions.filter((s) => s.pinned);
  const rest = sessions.filter((s) => !s.pinned);

  const now = Date.now();
  const dayMs = 86_400_000;
  const buckets: Record<string, SessionSummary[]> = {
    Today: [],
    Yesterday: [],
    "Previous 7 Days": [],
    Older: [],
  };
  for (const s of rest) {
    const ageDays = Math.floor((now - new Date(s.created_at).getTime()) / dayMs);
    if (ageDays < 1) buckets.Today.push(s);
    else if (ageDays < 2) buckets.Yesterday.push(s);
    else if (ageDays < 7) buckets["Previous 7 Days"].push(s);
    else buckets.Older.push(s);
  }

  const groups: Group[] = [];
  if (pinned.length > 0) groups.push({ label: "Pinned", items: pinned });
  for (const label of ["Today", "Yesterday", "Previous 7 Days", "Older"]) {
    if (buckets[label].length > 0) groups.push({ label, items: buckets[label] });
  }
  return groups;
}

export function Sidebar({
  onNewResearch,
  onSelectSession,
  onSessionDeleted,
  refreshKey,
  activeSessionId,
}: {
  onNewResearch: () => void;
  onSelectSession: (session: SessionSummary) => void;
  onSessionDeleted: (id: string) => void;
  refreshKey: number;
  activeSessionId: string | null;
}) {
  const [light, setLight] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [deleteBlockedId, setDeleteBlockedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const handle = setTimeout(() => {
      listSessions(query || undefined)
        .then((result) => {
          if (!cancelled) setSessions(result);
        })
        .catch(() => {
          if (!cancelled) setSessions([]);
        });
    }, query ? SEARCH_DEBOUNCE_MS : 0);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [refreshKey, query]);

  const toggleTheme = () => {
    setLight((prev) => {
      const next = !prev;
      document.documentElement.classList.toggle("dark", !next);
      return next;
    });
  };

  const startRename = (session: SessionSummary) => {
    setConfirmDeleteId(null);
    setEditingId(session.id);
    setEditingTitle(session.title);
  };

  const commitRename = async (id: string) => {
    const title = editingTitle.trim();
    setEditingId(null);
    if (!title) return;
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
    try {
      await renameSession(id, title);
    } catch {
      // Best-effort: a failed rename just falls out of sync until the next list refresh.
    }
  };

  const togglePin = async (session: SessionSummary) => {
    setPendingId(session.id);
    try {
      await setSessionPinned(session.id, !session.pinned);
      setSessions(await listSessions(query || undefined));
    } catch {
      // Ignore — the pin state stays whatever it last successfully was.
    } finally {
      setPendingId(null);
    }
  };

  const confirmDelete = async (id: string) => {
    setConfirmDeleteId(null);
    setPendingId(id);
    try {
      await deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      onSessionDeleted(id);
    } catch (err) {
      if (err instanceof SessionInProgressError) {
        setDeleteBlockedId(id);
        setTimeout(() => {
          setDeleteBlockedId((current) => (current === id ? null : current));
        }, 2500);
      }
      // Otherwise ignore — the row stays in the list if the delete call failed.
    } finally {
      setPendingId(null);
    }
  };

  const groups = groupSessions(sessions);

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
      <div className="flex items-center gap-2 px-4 pt-5 pb-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500 text-white">
          <BarChart3 className="h-5 w-5" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold">Market Research Agent</div>
          <div className="text-[10px] tracking-wide text-muted-foreground">AGENTDROPS</div>
        </div>
      </div>

      <div className="px-4 pb-3">
        <button
          onClick={onNewResearch}
          className="flex w-full items-center justify-center gap-2 rounded-md border bg-background/40 py-2 text-sm font-medium transition-colors hover:bg-accent"
        >
          <Plus className="h-4 w-4" />
          New research
        </button>
      </div>

      <div className="px-4 pb-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sessions..."
            className="w-full rounded-md border bg-background/40 py-1.5 pl-8 pr-7 text-xs outline-none placeholder:text-muted-foreground focus:border-ring"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      <div className="mt-1 flex-1 overflow-y-auto px-4">
        {groups.map((group) => (
          <div key={group.label} className="mb-4">
            <div className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground">
              {group.label.toUpperCase()}
            </div>
            <ul className="space-y-0.5">
              {group.items.map((s) => (
                <li
                  key={s.id}
                  className={cn(
                    "group/row relative rounded-md",
                    activeSessionId === s.id && "bg-accent"
                  )}
                >
                  {deleteBlockedId === s.id ? (
                    <div className="flex items-center px-2 py-2 text-xs text-muted-foreground">
                      <span className="truncate">
                        Still researching — try again once it&apos;s done.
                      </span>
                    </div>
                  ) : confirmDeleteId === s.id ? (
                    <div className="flex items-center justify-between gap-2 px-2 py-2 text-xs">
                      <span className="truncate text-muted-foreground">Delete this session?</span>
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          onClick={() => confirmDelete(s.id)}
                          className="rounded px-2 py-1 font-medium text-destructive hover:bg-destructive/10"
                        >
                          Delete
                        </button>
                        <button
                          onClick={() => setConfirmDeleteId(null)}
                          className="rounded px-2 py-1 text-muted-foreground hover:bg-accent"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : editingId === s.id ? (
                    <div className="flex items-center gap-1 px-2 py-1.5">
                      <input
                        autoFocus
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitRename(s.id);
                          if (e.key === "Escape") setEditingId(null);
                        }}
                        onBlur={() => commitRename(s.id)}
                        className="w-full rounded border bg-background px-1.5 py-1 text-sm outline-none focus:border-ring"
                      />
                      <button
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => commitRename(s.id)}
                        className="shrink-0 text-muted-foreground hover:text-foreground"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1 py-1">
                      <button
                        type="button"
                        onClick={() => onSelectSession(s)}
                        className="min-w-0 flex-1 px-2 py-1 text-left text-sm hover:text-foreground"
                      >
                        <div className="flex items-center gap-1.5 truncate text-foreground/90">
                          {s.pinned && <Pin className="h-3 w-3 shrink-0 text-blue-500" />}
                          <span className="truncate">{s.title}</span>
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {timeAgo(s.created_at)}
                          {s.status !== "done" && ` · ${s.status}`}
                        </div>
                      </button>
                      <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover/row:opacity-100">
                        {pendingId === s.id ? (
                          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin text-muted-foreground" />
                        ) : (
                          <>
                            <button
                              title={s.pinned ? "Unpin" : "Pin"}
                              onClick={() => togglePin(s)}
                              className="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                            >
                              {s.pinned ? (
                                <PinOff className="h-3.5 w-3.5" />
                              ) : (
                                <Pin className="h-3.5 w-3.5" />
                              )}
                            </button>
                            <button
                              title="Rename"
                              onClick={() => startRename(s)}
                              className="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button
                              title="Delete"
                              onClick={() => setConfirmDeleteId(s.id)}
                              className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
        {groups.length === 0 && (
          <div className="px-1 py-2 text-xs text-muted-foreground">
            {query ? "No sessions match your search." : "No research yet."}
          </div>
        )}
      </div>

      <div className="space-y-2 border-t px-4 py-4">
        <button
          onClick={toggleTheme}
          className="flex w-full items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-accent"
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
