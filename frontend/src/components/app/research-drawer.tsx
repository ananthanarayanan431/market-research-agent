"use client";

import { CheckCircle2, ChevronDown, Circle, Loader2, X } from "lucide-react";
import { ProgressStep, ResearchSource } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export type DrawerMode = "progress" | "report" | "table";

export function ResearchDrawer({
  title,
  mode,
  steps,
  sources,
  report,
  isRunning,
  onClose,
}: {
  title: string;
  mode: DrawerMode;
  steps: ProgressStep[];
  sources: ResearchSource[];
  report: string | null;
  isRunning: boolean;
  onClose: () => void;
}) {
  return (
    <div className="flex h-full w-full flex-col border-l bg-card">
      <div className="flex items-center justify-between border-b px-5 py-3">
        <div className="truncate text-sm font-semibold">
          {mode === "progress" ? title : `Deep Research: ${title}`}
        </div>
        <div className="flex items-center gap-3">
          {mode !== "progress" && (
            <button className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
              Show thinking
              <ChevronDown className="h-3.5 w-3.5" />
            </button>
          )}
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-5">
        {mode === "progress" && (
          <ProgressView steps={steps} sources={sources} isRunning={isRunning} />
        )}
        {mode === "report" && (
          <ReportView title={title} report={report} sourceCount={sources.length} />
        )}
        {mode === "table" && <TableViewMode title={title} sources={sources} />}
      </div>
    </div>
  );
}

function ProgressView({
  steps,
  sources,
  isRunning,
}: {
  steps: ProgressStep[];
  sources: ResearchSource[];
  isRunning: boolean;
}) {
  return (
    <div className="space-y-6">
      <ul className="space-y-3">
        {steps.map((step, i) => {
          const isLast = i === steps.length - 1;
          const status = isLast && isRunning ? "active" : "done";
          return (
            <li key={`${step.title}-${i}`} className="flex gap-2">
              <div className="mt-1 shrink-0">
                {status === "done" ? (
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                ) : (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />
                )}
              </div>
              <div>
                <div className="text-sm font-medium text-foreground">{step.title}</div>
                {status === "active" && step.detail && (
                  <div className="mt-1 text-xs italic text-muted-foreground">
                    {step.detail}
                  </div>
                )}
              </div>
            </li>
          );
        })}
        {steps.length === 0 && (
          <li className="flex gap-2">
            <Circle className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground/40" />
            <div className="text-sm text-muted-foreground">Waiting to start...</div>
          </li>
        )}
      </ul>

      {sources.length > 0 && (
        <div>
          <div className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground">
            {sources.length} SOURCES REVIEWED
          </div>
          <div className="grid grid-cols-1 gap-2">
            {sources.map((s, i) => (
              <div
                key={`${s.topic}-${i}`}
                className="flex items-start gap-2 rounded-md border p-2"
              >
                <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-muted text-[10px] font-semibold">
                  {s.topic.charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0">
                  <div className="truncate text-xs font-medium">{s.topic}</div>
                  <div className="truncate text-[11px] text-muted-foreground">
                    {s.summary}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ReportView({
  title,
  report,
  sourceCount,
}: {
  title: string;
  report: string | null;
  sourceCount: number;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold leading-snug">
          Deep Research: {title}
        </h2>
        <div className="mt-1 text-xs text-muted-foreground">
          {sourceCount} sources reviewed
        </div>
      </div>

      <div className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
        {report ?? "Report not available yet."}
      </div>

      <div className="flex gap-2 border-t pt-4">
        <button className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent">
          Copy report
        </button>
        <button className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent">
          Export as PDF
        </button>
      </div>
    </div>
  );
}

function TableViewMode({ title, sources }: { title: string; sources: ResearchSource[] }) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold leading-snug">
          Deep Research: {title}
        </h2>
        <div className="mt-1 text-xs text-muted-foreground">
          {sources.length} sources reviewed
        </div>
      </div>

      {sources.length > 0 ? (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Topic</TableHead>
                <TableHead>Finding</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.map((s, i) => (
                <TableRow key={`${s.topic}-${i}`}>
                  <TableCell className="font-medium">{s.topic}</TableCell>
                  <TableCell className="text-muted-foreground">{s.summary}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
          No sourced findings yet — a structured metric/value breakdown isn&apos;t available
          until the writer produces one; showing per-topic research findings instead.
        </div>
      )}

      <div className="flex gap-2 border-t pt-4">
        <button className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent">
          Copy table
        </button>
        <button className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent">
          Export as Excel
        </button>
      </div>
    </div>
  );
}
