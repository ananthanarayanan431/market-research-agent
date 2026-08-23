"use client";

import { useEffect, useState } from "react";
import { FileText, Link2, Loader2, Trash2, Upload, X } from "lucide-react";
import {
  addContextHubUrl,
  deleteContextHubDocument,
  listContextHubDocuments,
  uploadContextHubFile,
} from "@/lib/api";
import { ContextHubDocument } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<ContextHubDocument["status"], string> = {
  processing: "Processing...",
  ready: "Ready",
  failed: "Failed",
};

export function ContextHubPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [documents, setDocuments] = useState<ContextHubDocument[]>([]);
  const [urlInput, setUrlInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    listContextHubDocuments()
      .then(setDocuments)
      .catch(() => setError("Couldn't load Context Hub documents."));
  };

  useEffect(() => {
    if (open) refresh();
  }, [open]);

  const handleFileUpload = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      await uploadContextHubFile(file);
      refresh();
    } catch {
      setError(`Couldn't upload ${file.name}.`);
    } finally {
      setBusy(false);
    }
  };

  const handleAddUrl = async () => {
    const url = urlInput.trim();
    if (!url) return;
    setBusy(true);
    setError(null);
    try {
      await addContextHubUrl(url);
      setUrlInput("");
      refresh();
    } catch {
      setError("Couldn't add that URL.");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (id: string) => {
    setDocuments((prev) => prev.filter((d) => d.id !== id));
    try {
      await deleteContextHubDocument(id);
    } catch {
      refresh(); // roll back the optimistic removal if the delete failed
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-lg border bg-background shadow-lg">
        <div className="flex items-center justify-between border-b px-5 py-4">
          <h2 className="text-sm font-semibold">Context Hub</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 border-b px-5 py-4">
          <label
            className={cn(
              "flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed py-3 text-sm text-muted-foreground hover:bg-accent",
              busy && "pointer-events-none opacity-60"
            )}
          >
            <Upload className="h-4 w-4" />
            Upload PDF, DOCX, TXT, or CSV
            <input
              type="file"
              accept=".pdf,.docx,.txt,.csv"
              className="hidden"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFileUpload(file);
                e.target.value = "";
              }}
            />
          </label>

          <div className="flex items-center gap-2">
            <input
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddUrl()}
              placeholder="https://internal.example.com/wiki/..."
              disabled={busy}
              className="flex-1 rounded-md border bg-background/40 px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus:border-ring"
            />
            <button
              onClick={handleAddUrl}
              disabled={busy || !urlInput.trim()}
              className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
            >
              <Link2 className="h-3.5 w-3.5" />
              Add
            </button>
          </div>
          {error && <div className="text-xs text-destructive">{error}</div>}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-3">
          {documents.length === 0 ? (
            <div className="py-6 text-center text-xs text-muted-foreground">
              Nothing uploaded yet.
            </div>
          ) : (
            <ul className="space-y-1">
              {documents.map((doc) => (
                <li
                  key={doc.id}
                  className="flex items-center gap-2 rounded-md px-2 py-2 hover:bg-accent"
                >
                  {doc.source_type === "file" ? (
                    <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <Link2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm">{doc.title}</div>
                    <div
                      className={cn(
                        "text-xs",
                        doc.status === "failed" ? "text-destructive" : "text-muted-foreground"
                      )}
                    >
                      {doc.status === "processing" && (
                        <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />
                      )}
                      {STATUS_LABEL[doc.status]}
                      {doc.status === "failed" && doc.error ? `: ${doc.error}` : ""}
                    </div>
                  </div>
                  <button
                    title="Delete"
                    onClick={() => handleDelete(doc.id)}
                    className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
