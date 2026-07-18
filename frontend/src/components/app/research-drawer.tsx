"use client";

import { CheckCircle2, ChevronDown, Circle, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PROGRESS_STEPS,
  REPORT_SECTIONS,
  SOURCES,
  STAT_CARDS,
  TABLE_ROWS,
} from "@/lib/mock-data";
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
  stepIndex,
  onClose,
}: {
  title: string;
  mode: DrawerMode;
  stepIndex: number;
  onClose: () => void;
}) {
  const visibleSources =
    mode === "progress"
      ? SOURCES.slice(0, Math.max(0, (stepIndex - 1) * 6))
      : SOURCES;

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
          <ProgressView stepIndex={stepIndex} sources={visibleSources} />
        )}
        {mode === "report" && <ReportView title={title} />}
        {mode === "table" && <TableViewMode title={title} />}
      </div>
    </div>
  );
}

function ProgressView({
  stepIndex,
  sources,
}: {
  stepIndex: number;
  sources: typeof SOURCES;
}) {
  return (
    <div className="space-y-6">
      <ul className="space-y-3">
        {PROGRESS_STEPS.map((step, i) => {
          const status =
            i < stepIndex ? "done" : i === stepIndex ? "active" : "pending";
          return (
            <li key={step.title} className="flex gap-2">
              <div className="mt-1 shrink-0">
                {status === "done" && (
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                )}
                {status === "active" && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />
                )}
                {status === "pending" && (
                  <Circle className="h-3.5 w-3.5 text-muted-foreground/40" />
                )}
              </div>
              <div>
                <div
                  className={cn(
                    "text-sm",
                    status === "pending"
                      ? "text-muted-foreground"
                      : "font-medium text-foreground"
                  )}
                >
                  {step.title}
                </div>
                {status === "active" && step.detail && (
                  <div className="mt-1 text-xs italic text-muted-foreground">
                    {step.detail}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {sources.length > 0 && (
        <div>
          <div className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground">
            {sources.length} SOURCES REVIEWED
          </div>
          <div className="grid grid-cols-2 gap-2">
            {sources.map((s, i) => (
              <div
                key={`${s.domain}-${i}`}
                className="flex items-start gap-2 rounded-md border p-2"
              >
                <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-muted text-[10px] font-semibold">
                  {s.letter}
                </div>
                <div className="min-w-0">
                  <div className="truncate text-xs font-medium">
                    {s.domain}
                  </div>
                  <div className="truncate text-[11px] text-muted-foreground">
                    {s.blurb}
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

function ReportView({ title }: { title: string }) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold leading-snug">
          Deep Research: {title}
        </h2>
        <div className="mt-1 text-xs text-muted-foreground">
          Generated Jul 18, 2026 · 24 sources · confidence: high
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {STAT_CARDS.map((card) => (
          <div key={card.label} className="rounded-md border p-3">
            <div className="text-[10px] font-medium tracking-wide text-muted-foreground">
              {card.label}
            </div>
            <div className="mt-1 text-xl font-bold">{card.value}</div>
            <div className="text-[11px] text-emerald-500">{card.sub}</div>
          </div>
        ))}
      </div>

      <div className="flex h-40 items-center justify-center rounded-md border border-dashed bg-muted/30 font-mono text-xs text-muted-foreground">
        [ market share / competitive landscape chart ]
      </div>

      <div className="space-y-5">
        {REPORT_SECTIONS.map((section) => (
          <div key={section.heading}>
            <h3 className="mb-1 text-sm font-semibold">{section.heading}</h3>
            <p className="text-sm leading-relaxed text-muted-foreground">
              {section.body}
            </p>
          </div>
        ))}
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

function TableViewMode({ title }: { title: string }) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold leading-snug">
          Deep Research: {title}
        </h2>
        <div className="mt-1 text-xs text-muted-foreground">
          Generated Jul 18, 2026 · 24 sources · confidence: high
        </div>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Metric</TableHead>
              <TableHead>Value</TableHead>
              <TableHead>Source</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {TABLE_ROWS.map((row) => (
              <TableRow key={row.metric}>
                <TableCell className="font-medium">{row.metric}</TableCell>
                <TableCell>{row.value}</TableCell>
                <TableCell className="text-muted-foreground">
                  {row.source}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

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
