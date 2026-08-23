"use client";

import { Children, isValidElement, ReactNode, useState } from "react";
import { CheckCircle2, Circle, Loader2, Maximize2, Minimize2, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import jsPDF from "jspdf";
import { ProgressStep, ResearchSource } from "@/lib/types";

export type DrawerMode = "progress" | "report";

function Strong({ children }: { children?: ReactNode }) {
  return <strong className="font-semibold text-foreground">{children}</strong>;
}

// react-markdown passes each override an mdast `node` prop alongside DOM attributes; these only
// forward `children` so that extra prop never leaks onto the rendered element.
const MARKDOWN_COMPONENTS = {
  h1: ({ children }: { children?: ReactNode }) => (
    <h1 className="mb-2 mt-4 text-lg font-semibold">{children}</h1>
  ),
  h2: ({ children }: { children?: ReactNode }) => (
    <h2 className="mb-2 mt-4 text-base font-semibold">{children}</h2>
  ),
  h3: ({ children }: { children?: ReactNode }) => (
    <h3 className="mb-1 mt-3 text-sm font-semibold">{children}</h3>
  ),
  p: ({ children }: { children?: ReactNode }) => (
    <p className="mb-3 text-sm leading-7 text-muted-foreground">{children}</p>
  ),
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="mb-4 space-y-3 pl-1 text-sm text-muted-foreground">{children}</ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="mb-4 list-decimal space-y-3 pl-5 text-sm text-muted-foreground">{children}</ol>
  ),
  li: ({ children }: { children?: ReactNode }) => {
    // Reports frequently emit "- **Label**: description" bullets. Rendered as plain text these
    // read as one undifferentiated wall — split the label onto its own line so it scans as a
    // heading, with the description indented below it.
    const items = Children.toArray(children);
    const [first, ...rest] = items;
    const restStartsWithColon = typeof rest[0] === "string" && /^:\s*/.test(rest[0]);

    if (isValidElement(first) && first.type === Strong && restStartsWithColon) {
      const trimmedRest = rest.map((item, i) =>
        i === 0 && typeof item === "string" ? item.replace(/^:\s*/, "") : item
      );
      return (
        <li className="list-none">
          <div className="mb-1 flex items-center gap-2">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-foreground/50" />
            <span className="text-sm font-semibold text-foreground">{first}</span>
          </div>
          <p className="ml-3.5 border-l pl-3 leading-7 text-muted-foreground">{trimmedRest}</p>
        </li>
      );
    }

    return <li className="list-disc leading-7 marker:text-muted-foreground/50">{children}</li>;
  },
  strong: Strong,
  table: ({ children }: { children?: ReactNode }) => (
    <div className="mb-3 overflow-x-auto rounded-md border">
      <table className="w-full text-sm">{children}</table>
    </div>
  ),
  th: ({ children }: { children?: ReactNode }) => (
    <th className="border-b bg-muted px-2 py-1 text-left font-medium">{children}</th>
  ),
  td: ({ children }: { children?: ReactNode }) => (
    <td className="border-b px-2 py-1 text-muted-foreground">{children}</td>
  ),
};

/** Dumps the report's markdown source into a paginated PDF — headings get bold/larger text,
 * everything else wraps as plain paragraphs. No layout engine, just enough to be a readable
 * downloadable artifact. */
function downloadReportAsPdf(title: string, report: string) {
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const marginX = 48;
  const marginBottom = 48;
  const maxWidth = doc.internal.pageSize.getWidth() - marginX * 2;
  const pageHeight = doc.internal.pageSize.getHeight();
  let y = 56;

  const ensureSpace = (lineHeight: number) => {
    if (y + lineHeight > pageHeight - marginBottom) {
      doc.addPage();
      y = 56;
    }
  };

  doc.setFont("helvetica", "bold");
  doc.setFontSize(16);
  for (const line of doc.splitTextToSize(title, maxWidth)) {
    ensureSpace(20);
    doc.text(line, marginX, y);
    y += 20;
  }
  y += 8;

  for (const rawLine of report.split("\n")) {
    const line = rawLine.trimEnd();
    if (line.trim() === "") {
      y += 10;
      continue;
    }
    const headingMatch = /^(#{1,6})\s+(.*)/.exec(line);
    if (headingMatch) {
      const level = headingMatch[1].length;
      doc.setFont("helvetica", "bold");
      doc.setFontSize(Math.max(11, 16 - level));
      for (const wrapped of doc.splitTextToSize(headingMatch[2], maxWidth)) {
        ensureSpace(18);
        doc.text(wrapped, marginX, y);
        y += 18;
      }
      y += 4;
      continue;
    }
    doc.setFont("helvetica", "normal");
    doc.setFontSize(11);
    for (const wrapped of doc.splitTextToSize(line, maxWidth)) {
      ensureSpace(15);
      doc.text(wrapped, marginX, y);
      y += 15;
    }
  }

  const fileSlug = title.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  doc.save(`${fileSlug || "research-report"}.pdf`);
}

function CopyButton({ label, text }: { label: string; text: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access denied — button just won't flip to "Copied".
    }
  };

  return (
    <button
      onClick={copy}
      className="rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-accent"
    >
      {copied ? "Copied!" : label}
    </button>
  );
}

export function ResearchDrawer({
  title,
  mode,
  steps,
  sources,
  report,
  isRunning,
  expanded,
  onToggleExpand,
  onClose,
}: {
  title: string;
  mode: DrawerMode;
  steps: ProgressStep[];
  sources: ResearchSource[];
  report: string | null;
  isRunning: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
  onClose: () => void;
}) {
  return (
    <div className="flex h-full w-full flex-col border-l bg-card">
      <div className="flex items-center justify-between border-b px-5 py-3">
        <div className="flex min-w-0 items-center gap-2">
          {isRunning ? (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-500" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
          )}
          <div className="truncate text-sm font-semibold">
            {mode === "progress" ? title : `Deep Research: ${title}`}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            onClick={onToggleExpand}
            aria-label={expanded ? "Exit full screen" : "Expand to full screen"}
            className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            {expanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
          <button
            onClick={onClose}
            aria-label="Close research panel"
            className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-5">
        <div className="mx-auto max-w-3xl">
          {mode === "progress" && (
            <ProgressView steps={steps} sources={sources} isRunning={isRunning} />
          )}
          {mode === "report" && (
            <ReportView title={title} report={report} sourceCount={sources.length} />
          )}
        </div>
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
          const active = step.active && isRunning;
          return (
            <li key={`${step.title}-${i}`} className="flex gap-2">
              <div className="mt-1 shrink-0">
                {active ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                )}
              </div>
              <div>
                <div className="text-sm font-medium text-foreground">{step.title}</div>
                {active && step.detail && (
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
            <Circle className="mt-1 h-3.5 w-3.5 shrink-0 animate-pulse text-muted-foreground/40" />
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
                className="flex items-start gap-2 rounded-md border p-2 transition-colors hover:bg-accent/50"
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

      <div className="text-sm leading-relaxed">
        {report ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
            {report}
          </ReactMarkdown>
        ) : (
          <span className="text-muted-foreground">Report not available yet.</span>
        )}
      </div>

      <div className="flex gap-2 border-t pt-4">
        <CopyButton label="Copy report" text={report ?? ""} />
        <button
          onClick={() => report && downloadReportAsPdf(`Deep Research: ${title}`, report)}
          disabled={!report}
          className="rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
        >
          Download PDF
        </button>
      </div>
    </div>
  );
}
