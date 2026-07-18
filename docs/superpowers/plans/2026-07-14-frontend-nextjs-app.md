# Frontend: Next.js App Wired to the Real Backend API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Deep Research Market Agent frontend described in `docs/ui-builder-system-prompt.md` — New Run, Run Detail (live progress → report), History — as a real Next.js app wired to the FastAPI backend from `docs/superpowers/plans/2026-07-14-backend-research-api-worker.md` (no mocked/fixture data), styled with an acontext.io-inspired visual identity (light-first, high-contrast, blue accent, generous whitespace, monospace accents for the live event feed).

**Architecture:** Next.js 15 App Router + TypeScript + Tailwind CSS + shadcn/ui. Server-rendered pages fetch initial run state from the FastAPI REST API; the Run Detail page opens a browser `EventSource` against the backend's SSE endpoint while a run is in progress, then switches to a static reading view once the run reaches a terminal state.

**Tech Stack:** Next.js (App Router), React, TypeScript, Tailwind CSS v4, shadcn/ui, `react-markdown` (report rendering), Vitest + React Testing Library (component/unit tests).

## Global Constraints

- Lives in `frontend/`, sibling to `backend/` (repo root).
- Backend base URL from `NEXT_PUBLIC_API_BASE_URL` (env var, default `http://localhost:8000` in `.env.local` for dev) — never hardcode the URL in components.
- Every API field name matches the backend contract exactly (snake_case, per `docs/ui-builder-system-prompt.md` §4 and the Pydantic schemas in Plan 2's Task 4/16) — do not camelCase fields when mapping JSON responses.
- No mocked/fixture data anywhere in application code — all data comes from real `fetch`/`EventSource` calls against the backend from Plan 2. (Component tests may construct literal in-memory objects matching the types to render a component in isolation — that is normal unit testing, not app-level mocking.)
- TypeScript strict mode (`tsconfig.json` `"strict": true`, from `create-next-app` defaults) — no `any` in application code; use the shared types in `lib/types.ts`.
- Support both light and dark mode via shadcn's CSS-variable theme; the live event feed panel stays console-dark even on the light theme (per `docs/ui-builder-system-prompt.md` §3).
- One commit per task, following the existing repo commit style (`feat(frontend): ...`).
- This plan assumes Plan 2's backend is reachable at `NEXT_PUBLIC_API_BASE_URL` while running dev-server-based manual checks; automated tests in Tasks 2-7 use component-level fakes/mocks for `fetch`/`EventSource`, not a live backend, so they run without the backend up.

---

### Task 1: Next.js scaffold, Tailwind/shadcn setup, and acontext-inspired theme

**Files:**
- Create: `frontend/` (via `create-next-app`)
- Modify: `frontend/app/globals.css`
- Modify: `frontend/app/layout.tsx`
- Create: `frontend/components/nav.tsx`
- Create: `frontend/components/theme-toggle.tsx`
- Create: `frontend/components/theme-provider.tsx`
- Modify: `docker-compose.yml` (repo root, adding the `frontend` service)
- Modify: `.env.example` (repo root)
- Create: `frontend/.env.local.example`

**Interfaces:**
- Produces: a running Next.js app shell with global nav (New Run, History), light/dark theme toggle, and the acontext-inspired token set in `globals.css` — consumed by every subsequent task's pages.

- [ ] **Step 1: Scaffold the app**

Run from the repo root:

```bash
npx create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir=false --import-alias "@/*" --use-npm
```

When prompted, accept the defaults (App Router: yes, `src/` directory: no, Turbopack: your call).

- [ ] **Step 2: Initialize shadcn/ui**

Run: `cd frontend && npx shadcn@latest init`

When prompted: TypeScript — yes; style — default; base color — **Neutral**; CSS variables — yes. (Exact prompts vary by shadcn CLI version — if flags are available in your installed version to answer non-interactively, e.g. `--base-color neutral --yes`, use them; otherwise answer interactively as above.)

- [ ] **Step 3: Add the shadcn components this app will use**

Run: `cd frontend && npx shadcn@latest add button input textarea card badge table separator tabs skeleton scroll-area`

- [ ] **Step 4: Add `react-markdown`**

Run: `cd frontend && npm install react-markdown remark-gfm`

- [ ] **Step 5: Add Vitest + React Testing Library**

Run: `cd frontend && npm install -D vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/jest-dom`

Create `frontend/vitest.config.ts`:

```typescript
import react from "@vitejs/plugin-react";
import path from "path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, ".") },
  },
});
```

Create `frontend/vitest.setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
```

In `frontend/package.json`, add to `"scripts"`:

```json
    "test": "vitest run"
```

- [ ] **Step 6: Set the acontext-inspired theme tokens**

Replace the `:root` and `.dark` variable blocks in `frontend/app/globals.css` (generated by shadcn init) with:

```css
:root {
  --radius: 0.5rem;
  --background: oklch(1 0 0);
  --foreground: oklch(0.145 0 0);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.145 0 0);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.145 0 0);
  --primary: oklch(0.546 0.215 262.9);
  --primary-foreground: oklch(0.98 0 0);
  --secondary: oklch(0.97 0 0);
  --secondary-foreground: oklch(0.205 0 0);
  --muted: oklch(0.97 0 0);
  --muted-foreground: oklch(0.556 0 0);
  --accent: oklch(0.97 0 0);
  --accent-foreground: oklch(0.205 0 0);
  --destructive: oklch(0.577 0.245 27.325);
  --border: oklch(0.922 0 0);
  --input: oklch(0.922 0 0);
  --ring: oklch(0.546 0.215 262.9);
}

.dark {
  --background: oklch(0.145 0 0);
  --foreground: oklch(0.985 0 0);
  --card: oklch(0.205 0 0);
  --card-foreground: oklch(0.985 0 0);
  --popover: oklch(0.205 0 0);
  --popover-foreground: oklch(0.985 0 0);
  --primary: oklch(0.65 0.2 262.9);
  --primary-foreground: oklch(0.145 0 0);
  --secondary: oklch(0.269 0 0);
  --secondary-foreground: oklch(0.985 0 0);
  --muted: oklch(0.269 0 0);
  --muted-foreground: oklch(0.708 0 0);
  --accent: oklch(0.269 0 0);
  --accent-foreground: oklch(0.985 0 0);
  --destructive: oklch(0.704 0.191 22.216);
  --border: oklch(1 0 0 / 10%);
  --input: oklch(1 0 0 / 15%);
  --ring: oklch(0.65 0.2 262.9);
}
```

(Leave the rest of the generated file — `@theme inline` mappings, `@layer base` rules — as shadcn's `init` produced them; only the token values above change.)

- [ ] **Step 7: Build the theme provider and toggle**

Run: `cd frontend && npm install next-themes`

Create `frontend/components/theme-provider.tsx`:

```tsx
"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

export function ThemeProvider({ children, ...props }: ComponentProps<typeof NextThemesProvider>) {
  return <NextThemesProvider {...props}>{children}</NextThemesProvider>;
}
```

Create `frontend/components/theme-toggle.tsx`:

```tsx
"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Toggle theme"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
    >
      <Sun className="h-4 w-4 dark:hidden" />
      <Moon className="hidden h-4 w-4 dark:block" />
    </Button>
  );
}
```

- [ ] **Step 8: Build the global nav**

Create `frontend/components/nav.tsx`:

```tsx
import Link from "next/link";

import { ThemeToggle } from "@/components/theme-toggle";

export function Nav() {
  return (
    <header className="border-b border-border">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <Link href="/" className="text-sm font-semibold tracking-tight">
          Deep Research Market Agent
        </Link>
        <nav className="flex items-center gap-6 text-sm">
          <Link href="/" className="text-muted-foreground hover:text-foreground">
            New Run
          </Link>
          <Link href="/runs" className="text-muted-foreground hover:text-foreground">
            History
          </Link>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
```

- [ ] **Step 9: Wire the root layout**

Replace the contents of `frontend/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { Nav } from "@/components/nav";
import { ThemeProvider } from "@/components/theme-provider";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Deep Research Market Agent",
  description: "Autonomous market research and idea generation.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem>
          <Nav />
          <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
        </ThemeProvider>
      </body>
    </html>
  );
}
```

- [ ] **Step 10: Add environment templates**

Create `frontend/.env.local.example`:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

In `.env.example` (repo root), append:

```bash

NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

- [ ] **Step 11: Add the frontend service to docker-compose.yml**

In `docker-compose.yml` (repo root), add after the `worker` service:

```yaml
  frontend:
    build: ./frontend
    environment:
      NEXT_PUBLIC_API_BASE_URL: http://localhost:8000
    ports: ["3000:3000"]
    depends_on:
      - backend
```

Create `frontend/Dockerfile`:

```dockerfile
FROM node:22-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
```

- [ ] **Step 12: Verify the app boots**

Run: `cd frontend && npm run dev &` then `curl -sf http://localhost:3000 > /dev/null && echo OK`
Expected: `OK` (stop the dev server afterward with `kill %1` or Ctrl-C).

- [ ] **Step 13: Run the test runner and linter**

Run: `cd frontend && npm test && npm run lint`
Expected: Vitest reports "no test files" (none written yet — expected) with exit code 0; ESLint passes with no errors.

- [ ] **Step 14: Commit**

```bash
git add frontend docker-compose.yml .env.example
git commit -m "feat(frontend): scaffold Next.js app with shadcn/ui and acontext-inspired theme"
```

---

### Task 2: Shared types and API client

**Files:**
- Create: `frontend/lib/types.ts`
- Create: `frontend/lib/api.ts`
- Create: `frontend/lib/use-run-events.ts`
- Test: `frontend/lib/api.test.ts`
- Test: `frontend/lib/use-run-events.test.ts`

**Interfaces:**
- Produces: `RunStatus`, `RunSummary`, `SourceOut`, `IdeaOnePager`, `RunDetail`, `RunListResponse`, `RunEvent` types (mirroring Plan 2 Task 4/15's Pydantic schemas field-for-field); `createRun(input: {topic: string; constraints?: string}): Promise<{run_id: string}>`, `listRuns(params?: {limit?: number; offset?: number}): Promise<RunListResponse>`, `getRun(runId: string): Promise<RunDetail>`, `createExport(runId: string, format: "pdf" | "xlsx"): Promise<{export_id: string}>`, `getExportStatus(runId: string, format: "pdf" | "xlsx"): Promise<{status: "generating"} | {redirectUrl: string}>` (all consumed by every page task below); `useRunEvents(runId: string, options: {enabled: boolean}): {events: RunEvent[]; isConnected: boolean}` (a React hook wrapping `EventSource`, consumed by Task 5's progress view).

- [ ] **Step 1: Write the shared types**

Create `frontend/lib/types.ts`:

```typescript
export type RunStatus = "queued" | "running" | "completed" | "failed";

export interface RunSummary {
  id: string;
  topic: string;
  status: RunStatus;
  created_at: string;
  updated_at: string;
}

export interface RunListResponse {
  runs: RunSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface SourceOut {
  id: string;
  tool_name: "exa" | "tavily" | "newsapi" | "reddit";
  url: string;
  title: string;
  snippet: string;
  retrieved_at: string;
}

export interface IdeaOnePager {
  problem_statement: string;
  recommended_direction: string;
  key_assumptions: string[];
  mvp_scope: string[];
  not_doing: string[];
  open_questions: string[];
}

export interface RunDetail {
  id: string;
  topic: string;
  constraints: string | null;
  status: RunStatus;
  research_brief: string | null;
  final_report: string | null;
  idea_onepager: IdeaOnePager | null;
  sources: SourceOut[];
  error: string | null;
  created_at: string;
  updated_at: string;
}

export type NodeName =
  | "write_research_brief"
  | "supervisor"
  | "researcher"
  | "compress_research"
  | "final_report_generation"
  | "idea_refine_generation";

export type EventType = "started" | "tool_call" | "progress" | "completed" | "error";

export interface RunEvent {
  node_name: NodeName;
  event_type: EventType;
  message: string;
  payload?: Record<string, unknown>;
  created_at: string;
}
```

- [ ] **Step 2: Write the failing API client test**

Create `frontend/lib/api.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createExport, createRun, getExportStatus, getRun, listRuns } from "./api";

const originalFetch = global.fetch;

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://api.test";
});

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("createRun", () => {
  it("posts to /runs and returns the run id", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ run_id: "abc-123" }), { status: 201 })
    );

    const result = await createRun({ topic: "AI note-taking apps" });

    expect(result).toEqual({ run_id: "abc-123" });
    expect(global.fetch).toHaveBeenCalledWith(
      "http://api.test/runs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ topic: "AI note-taking apps" }),
      })
    );
  });
});

describe("listRuns", () => {
  it("builds query params and returns the parsed page", async () => {
    const page = { runs: [], total: 0, limit: 20, offset: 0 };
    global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(page), { status: 200 }));

    const result = await listRuns({ limit: 20, offset: 0 });

    expect(result).toEqual(page);
    expect(global.fetch).toHaveBeenCalledWith(
      "http://api.test/runs?limit=20&offset=0",
      expect.anything()
    );
  });
});

describe("getRun", () => {
  it("throws a descriptive error on 404", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 404 }));

    await expect(getRun("missing-id")).rejects.toThrow("Run not found");
  });
});

describe("createExport / getExportStatus", () => {
  it("createExport posts the requested format", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ export_id: "exp-1" }), { status: 201 })
    );

    const result = await createExport("run-1", "pdf");

    expect(result).toEqual({ export_id: "exp-1" });
    expect(global.fetch).toHaveBeenCalledWith(
      "http://api.test/runs/run-1/export",
      expect.objectContaining({ body: JSON.stringify({ format: "pdf" }) })
    );
  });

  it("getExportStatus returns generating on 202", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "generating" }), { status: 202 })
    );

    const result = await getExportStatus("run-1", "pdf");

    expect(result).toEqual({ status: "generating" });
  });

  it("getExportStatus returns the redirect URL on 303", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(null, { status: 303, headers: { Location: "https://minio.local/x.pdf" } })
    );

    const result = await getExportStatus("run-1", "pdf");

    expect(result).toEqual({ redirectUrl: "https://minio.local/x.pdf" });
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm test -- api.test.ts`
Expected: FAIL — `Cannot find module './api'`.

- [ ] **Step 4: Implement the API client**

Create `frontend/lib/api.ts`:

```typescript
import type { RunDetail, RunListResponse, RunStatus } from "./types";

function apiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

async function parseJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

export async function createRun(input: {
  topic: string;
  constraints?: string;
}): Promise<{ run_id: string }> {
  const response = await fetch(`${apiBaseUrl()}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    throw new Error(`Failed to create run (${response.status})`);
  }
  return parseJson(response);
}

export async function listRuns(
  params: { limit?: number; offset?: number } = {}
): Promise<RunListResponse> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const suffix = query.toString() ? `?${query.toString()}` : "";

  const response = await fetch(`${apiBaseUrl()}/runs${suffix}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to list runs (${response.status})`);
  }
  return parseJson(response);
}

export async function getRun(runId: string): Promise<RunDetail> {
  const response = await fetch(`${apiBaseUrl()}/runs/${runId}`, { cache: "no-store" });
  if (response.status === 404) {
    throw new Error("Run not found");
  }
  if (!response.ok) {
    throw new Error(`Failed to load run (${response.status})`);
  }
  return parseJson(response);
}

export async function createExport(
  runId: string,
  format: "pdf" | "xlsx"
): Promise<{ export_id: string }> {
  const response = await fetch(`${apiBaseUrl()}/runs/${runId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format }),
  });
  if (!response.ok) {
    throw new Error(`Failed to start export (${response.status})`);
  }
  return parseJson(response);
}

export async function getExportStatus(
  runId: string,
  format: "pdf" | "xlsx"
): Promise<{ status: "generating" } | { redirectUrl: string }> {
  const response = await fetch(`${apiBaseUrl()}/runs/${runId}/export/${format}`, {
    redirect: "manual",
  });
  if (response.status === 303 || response.type === "opaqueredirect") {
    const location = response.headers.get("Location") ?? "";
    return { redirectUrl: location };
  }
  if (response.status === 202) {
    return { status: "generating" };
  }
  throw new Error(`Failed to check export status (${response.status})`);
}

export function apiBaseUrlForEvents(runId: string): string {
  return `${apiBaseUrl()}/runs/${runId}/events`;
}

export type { RunDetail, RunListResponse, RunStatus };
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test -- api.test.ts`
Expected: all tests PASS.

Note: `redirect: "manual"` fetch behavior for same-origin vs cross-origin redirects differs across environments (jsdom/undici vs a real browser) — if the `getExportStatus` redirect test is flaky under the Vitest/jsdom `fetch` polyfill, assert on `response.headers.get("Location")` directly as done above (already environment-tolerant) rather than relying on `response.type`.

- [ ] **Step 6: Write the failing SSE hook test**

Create `frontend/lib/use-run-events.test.ts`:

```typescript
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRunEvents } from "./use-run-events";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }

  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  // @ts-expect-error -- test double replacing the browser global
  global.EventSource = FakeEventSource;
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://api.test";
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useRunEvents", () => {
  it("does nothing when disabled", () => {
    renderHook(() => useRunEvents("run-1", { enabled: false }));
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("accumulates events as they arrive and closes on the terminal event", async () => {
    const { result } = renderHook(() => useRunEvents("run-1", { enabled: true }));

    expect(FakeEventSource.instances).toHaveLength(1);
    const source = FakeEventSource.instances[0];

    source.emit({
      node_name: "write_research_brief", event_type: "started", message: "Starting",
      created_at: "2026-07-14T00:00:00Z",
    });
    source.emit({
      node_name: "idea_refine_generation", event_type: "completed", message: "Done",
      created_at: "2026-07-14T00:01:00Z",
    });

    await waitFor(() => expect(result.current.events).toHaveLength(2));
    expect(result.current.events[0].node_name).toBe("write_research_brief");
    expect(source.closed).toBe(true);
  });
});
```

- [ ] **Step 7: Run test to verify it fails**

Run: `cd frontend && npm test -- use-run-events.test.ts`
Expected: FAIL — `Cannot find module './use-run-events'`.

- [ ] **Step 8: Implement the SSE hook**

Create `frontend/lib/use-run-events.ts`:

```typescript
"use client";

import { useEffect, useRef, useState } from "react";

import { apiBaseUrlForEvents } from "./api";
import type { RunEvent } from "./types";

function isTerminal(event: RunEvent): boolean {
  return event.event_type === "error" || (
    event.node_name === "idea_refine_generation" && event.event_type === "completed"
  );
}

export function useRunEvents(
  runId: string,
  options: { enabled: boolean }
): { events: RunEvent[]; isConnected: boolean } {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!options.enabled) {
      return;
    }

    const source = new EventSource(apiBaseUrlForEvents(runId));
    sourceRef.current = source;
    setIsConnected(true);

    source.onmessage = (message) => {
      const parsed = JSON.parse(message.data) as RunEvent;
      setEvents((previous) => [...previous, parsed]);
      if (isTerminal(parsed)) {
        source.close();
        setIsConnected(false);
      }
    };

    source.onerror = () => {
      source.close();
      setIsConnected(false);
    };

    return () => {
      source.close();
      setIsConnected(false);
    };
  }, [runId, options.enabled]);

  return { events, isConnected };
}
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd frontend && npm test -- use-run-events.test.ts`
Expected: both tests PASS.

- [ ] **Step 10: Run the full test suite and linter**

Run: `cd frontend && npm test && npm run lint`
Expected: all tests pass; lint clean.

- [ ] **Step 11: Commit**

```bash
git add frontend/lib
git commit -m "feat(frontend): add API client, shared types, and SSE event hook"
```

---

### Task 3: New Run page (`/`)

**Files:**
- Modify: `frontend/app/page.tsx`
- Create: `frontend/components/run/new-run-form.tsx`
- Create: `frontend/components/run/recent-runs-list.tsx`
- Test: `frontend/components/run/new-run-form.test.tsx`

**Interfaces:**
- Consumes: `createRun`, `listRuns` from Task 2; shadcn `Button`, `Input`, `Textarea`, `Card` from Task 1.
- Produces: `NewRunForm` (client component, calls `createRun` then `router.push('/runs/{run_id}')`), `RecentRunsList` (server component, calls `listRuns({limit: 5})`), the composed `/` page.

- [ ] **Step 1: Write the failing form test**

Create `frontend/components/run/new-run-form.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));

import { NewRunForm } from "./new-run-form";

beforeEach(() => {
  pushMock.mockReset();
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://api.test";
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("NewRunForm", () => {
  it("submits the topic and redirects to the run detail page", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ run_id: "run-123" }), { status: 201 })
    );
    const user = userEvent.setup();

    render(<NewRunForm />);
    await user.type(screen.getByLabelText(/topic/i), "AI note-taking apps");
    await user.click(screen.getByRole("button", { name: /start research/i }));

    await vi.waitFor(() => expect(pushMock).toHaveBeenCalledWith("/runs/run-123"));
    expect(global.fetch).toHaveBeenCalledWith(
      "http://api.test/runs",
      expect.objectContaining({
        body: JSON.stringify({ topic: "AI note-taking apps", constraints: undefined }),
      })
    );
  });

  it("disables the submit button while the topic is empty", () => {
    render(<NewRunForm />);
    expect(screen.getByRole("button", { name: /start research/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- new-run-form.test.tsx`
Expected: FAIL — `Cannot find module './new-run-form'`.

- [ ] **Step 3: Implement the form**

Create `frontend/components/run/new-run-form.tsx`:

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createRun } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

export function NewRunForm() {
  const router = useRouter();
  const [topic, setTopic] = useState("");
  const [constraints, setConstraints] = useState("");
  const [showConstraints, setShowConstraints] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const { run_id } = await createRun({
        topic,
        constraints: constraints.trim() ? constraints.trim() : undefined,
      });
      router.push(`/runs/${run_id}`);
    } catch {
      setError("Could not start the research run. Please try again.");
      setIsSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <label htmlFor="topic" className="text-sm font-medium">
          Topic
        </label>
        <Input
          id="topic"
          placeholder="e.g. AI note-taking apps"
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          required
        />
      </div>

      <button
        type="button"
        className="self-start text-sm text-muted-foreground underline-offset-4 hover:underline"
        onClick={() => setShowConstraints((prev) => !prev)}
      >
        {showConstraints ? "Hide" : "Add"} constraints (optional)
      </button>

      {showConstraints && (
        <Textarea
          placeholder="e.g. focus on B2B, US market only"
          value={constraints}
          onChange={(event) => setConstraints(event.target.value)}
        />
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}

      <Button type="submit" disabled={!topic.trim() || isSubmitting} className="self-start">
        {isSubmitting ? "Starting…" : "Start Research"}
      </Button>
    </form>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- new-run-form.test.tsx`
Expected: both tests PASS.

- [ ] **Step 5: Implement the recent runs list**

Create `frontend/components/run/recent-runs-list.tsx`:

```tsx
import Link from "next/link";

import { listRuns } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive"> = {
  queued: "secondary",
  running: "default",
  completed: "secondary",
  failed: "destructive",
};

export async function RecentRunsList() {
  const { runs } = await listRuns({ limit: 5 });

  if (runs.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">Recent runs</h2>
        <Link href="/runs" className="text-sm text-primary hover:underline">
          View all
        </Link>
      </div>
      <ul className="flex flex-col gap-2">
        {runs.map((run) => (
          <li key={run.id}>
            <Link
              href={`/runs/${run.id}`}
              className="flex items-center justify-between rounded-md border border-border px-4 py-3 hover:bg-accent"
            >
              <span className="truncate text-sm">{run.topic}</span>
              <Badge variant={STATUS_VARIANT[run.status]}>{run.status}</Badge>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 6: Compose the page**

Replace `frontend/app/page.tsx`:

```tsx
import { Suspense } from "react";

import { NewRunForm } from "@/components/run/new-run-form";
import { RecentRunsList } from "@/components/run/recent-runs-list";

export default function HomePage() {
  return (
    <div className="mx-auto flex max-w-lg flex-col gap-12 py-12">
      <div className="flex flex-col gap-2 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">Research any market in minutes</h1>
        <p className="text-muted-foreground">
          Enter a topic and let the agent research the web, news, and community discussion for you.
        </p>
      </div>
      <NewRunForm />
      <Suspense fallback={null}>
        <RecentRunsList />
      </Suspense>
    </div>
  );
}
```

- [ ] **Step 7: Run the full test suite and linter**

Run: `cd frontend && npm test && npm run lint`
Expected: all tests pass; lint clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/app/page.tsx frontend/components/run/new-run-form.tsx frontend/components/run/recent-runs-list.tsx frontend/components/run/new-run-form.test.tsx
git commit -m "feat(frontend): add New Run page with topic form and recent runs list"
```

---

### Task 4: History page (`/runs`)

**Files:**
- Create: `frontend/app/runs/page.tsx`
- Create: `frontend/components/run/runs-table.tsx`
- Test: `frontend/components/run/runs-table.test.tsx`

**Interfaces:**
- Consumes: `listRuns` from Task 2; shadcn `Table`, `Badge` from Task 1.
- Produces: `RunsTable` (client component accepting `runs: RunSummary[]` and rendering the dense history table), the `/runs` page (server component reading `?page=` search param, calling `listRuns`, rendering pagination controls).

- [ ] **Step 1: Write the failing table test**

Create `frontend/components/run/runs-table.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunsTable } from "./runs-table";
import type { RunSummary } from "@/lib/types";

const runs: RunSummary[] = [
  {
    id: "run-1", topic: "AI note-taking apps", status: "completed",
    created_at: "2026-07-10T00:00:00Z", updated_at: "2026-07-10T00:05:00Z",
  },
  {
    id: "run-2", topic: "B2B expense tools", status: "failed",
    created_at: "2026-07-11T00:00:00Z", updated_at: "2026-07-11T00:05:00Z",
  },
];

describe("RunsTable", () => {
  it("renders one row per run with a link to its detail page", () => {
    render(<RunsTable runs={runs} />);

    const link = screen.getByRole("link", { name: /AI note-taking apps/i });
    expect(link).toHaveAttribute("href", "/runs/run-1");
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("shows an empty state when there are no runs", () => {
    render(<RunsTable runs={[]} />);
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- runs-table.test.tsx`
Expected: FAIL — `Cannot find module './runs-table'`.

- [ ] **Step 3: Implement the table**

Create `frontend/components/run/runs-table.tsx`:

```tsx
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { RunSummary } from "@/lib/types";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive"> = {
  queued: "secondary",
  running: "default",
  completed: "secondary",
  failed: "destructive",
};

export function RunsTable({ runs }: { runs: RunSummary[] }) {
  if (runs.length === 0) {
    return <p className="text-sm text-muted-foreground">No runs yet.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Topic</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.id}>
            <TableCell>
              <Link href={`/runs/${run.id}`} className="hover:underline">
                {run.topic}
              </Link>
            </TableCell>
            <TableCell>
              <Badge variant={STATUS_VARIANT[run.status]}>{run.status}</Badge>
            </TableCell>
            <TableCell className="text-muted-foreground">
              {new Date(run.created_at).toLocaleString()}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- runs-table.test.tsx`
Expected: both tests PASS.

- [ ] **Step 5: Implement the page**

Create `frontend/app/runs/page.tsx`:

```tsx
import Link from "next/link";

import { RunsTable } from "@/components/run/runs-table";
import { listRuns } from "@/lib/api";

const PAGE_SIZE = 20;

export default async function RunsHistoryPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string }>;
}) {
  const { page } = await searchParams;
  const currentPage = Math.max(1, Number(page ?? "1") || 1);
  const offset = (currentPage - 1) * PAGE_SIZE;

  const { runs, total } = await listRuns({ limit: PAGE_SIZE, offset });
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold tracking-tight">Run History</h1>
      <RunsTable runs={runs} />
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          {currentPage > 1 ? (
            <Link href={`/runs?page=${currentPage - 1}`} className="hover:underline">
              ← Previous
            </Link>
          ) : (
            <span />
          )}
          <span>
            Page {currentPage} of {totalPages}
          </span>
          {currentPage < totalPages ? (
            <Link href={`/runs?page=${currentPage + 1}`} className="hover:underline">
              Next →
            </Link>
          ) : (
            <span />
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Run the full test suite and linter**

Run: `cd frontend && npm test && npm run lint`
Expected: all tests pass; lint clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/app/runs/page.tsx frontend/components/run/runs-table.tsx frontend/components/run/runs-table.test.tsx
git commit -m "feat(frontend): add paginated History page"
```

---

### Task 5: Run Detail — live progress view

**Files:**
- Create: `frontend/components/run/phase-indicator.tsx`
- Create: `frontend/components/run/event-feed.tsx`
- Create: `frontend/components/run/sub-researcher-tracks.tsx`
- Create: `frontend/components/run/progress-view.tsx`
- Test: `frontend/components/run/phase-indicator.test.tsx`
- Test: `frontend/components/run/event-feed.test.tsx`
- Test: `frontend/components/run/sub-researcher-tracks.test.tsx`

**Interfaces:**
- Consumes: `RunEvent`, `NodeName` from Task 2's `lib/types.ts`; `useRunEvents` from Task 2.
- Produces: `PhaseIndicator({currentPhase: NodeName | null})`, `EventFeed({events: RunEvent[]})` (console-styled, auto-scrolling), `SubResearcherTracks({events: RunEvent[]})` (groups `researcher`/`compress_research` events by `payload.sub_topic` into parallel cards), `ProgressView({runId, initialStatus, onComplete})` (composes the three above over `useRunEvents`, consumed by Task 6's Run Detail page).

- [ ] **Step 1: Write the failing phase-indicator test**

Create `frontend/components/run/phase-indicator.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PhaseIndicator } from "./phase-indicator";

describe("PhaseIndicator", () => {
  it("highlights the current phase", () => {
    render(<PhaseIndicator currentPhase="researcher" />);
    const active = screen.getByText("Research");
    expect(active).toHaveAttribute("data-active", "true");
    expect(screen.getByText("Report")).toHaveAttribute("data-active", "false");
  });

  it("highlights nothing before the first event arrives", () => {
    render(<PhaseIndicator currentPhase={null} />);
    for (const label of ["Brief", "Research", "Compress", "Report", "Ideation"]) {
      expect(screen.getByText(label)).toHaveAttribute("data-active", "false");
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- phase-indicator.test.tsx`
Expected: FAIL — `Cannot find module './phase-indicator'`.

- [ ] **Step 3: Implement the phase indicator**

Create `frontend/components/run/phase-indicator.tsx`:

```tsx
import type { NodeName } from "@/lib/types";
import { cn } from "@/lib/utils";

const PHASES: { label: string; nodeNames: NodeName[] }[] = [
  { label: "Brief", nodeNames: ["write_research_brief"] },
  { label: "Research", nodeNames: ["supervisor", "researcher"] },
  { label: "Compress", nodeNames: ["compress_research"] },
  { label: "Report", nodeNames: ["final_report_generation"] },
  { label: "Ideation", nodeNames: ["idea_refine_generation"] },
];

export function PhaseIndicator({ currentPhase }: { currentPhase: NodeName | null }) {
  return (
    <ol className="flex items-center gap-2 text-sm">
      {PHASES.map((phase, index) => {
        const isActive = currentPhase !== null && phase.nodeNames.includes(currentPhase);
        return (
          <li key={phase.label} className="flex items-center gap-2">
            <span
              data-active={isActive}
              className={cn(
                "rounded-full px-3 py-1 text-muted-foreground",
                isActive && "bg-primary text-primary-foreground"
              )}
            >
              {phase.label}
            </span>
            {index < PHASES.length - 1 && <span className="text-muted-foreground">→</span>}
          </li>
        );
      })}
    </ol>
  );
}
```

(`cn` is the `clsx`/`tailwind-merge` helper shadcn's `init` already generated at `frontend/lib/utils.ts` — no change needed there.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- phase-indicator.test.tsx`
Expected: both tests PASS.

- [ ] **Step 5: Write the failing event-feed test**

Create `frontend/components/run/event-feed.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EventFeed } from "./event-feed";
import type { RunEvent } from "@/lib/types";

const events: RunEvent[] = [
  { node_name: "write_research_brief", event_type: "started", message: "Starting", created_at: "2026-07-14T00:00:00Z" },
  { node_name: "researcher", event_type: "tool_call", message: "Searching Reddit", created_at: "2026-07-14T00:01:00Z" },
];

describe("EventFeed", () => {
  it("renders one line per event with a node badge", () => {
    render(<EventFeed events={events} />);
    expect(screen.getByText("Starting")).toBeInTheDocument();
    expect(screen.getByText("Searching Reddit")).toBeInTheDocument();
    expect(screen.getAllByText("researcher")).not.toHaveLength(0);
  });

  it("shows a waiting message when there are no events yet", () => {
    render(<EventFeed events={[]} />);
    expect(screen.getByText(/waiting for the agent/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd frontend && npm test -- event-feed.test.tsx`
Expected: FAIL — `Cannot find module './event-feed'`.

- [ ] **Step 7: Implement the event feed**

Create `frontend/components/run/event-feed.tsx`:

```tsx
"use client";

import { useEffect, useRef } from "react";

import type { RunEvent } from "@/lib/types";

const EVENT_TYPE_COLOR: Record<string, string> = {
  started: "text-blue-400",
  tool_call: "text-amber-400",
  progress: "text-neutral-400",
  completed: "text-emerald-400",
  error: "text-red-400",
};

export function EventFeed({ events }: { events: RunEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  return (
    <div className="h-80 overflow-y-auto rounded-md bg-neutral-950 p-4 font-mono text-xs text-neutral-300">
      {events.length === 0 && <p className="text-neutral-500">Waiting for the agent to start…</p>}
      {events.map((event, index) => (
        <div key={index} className="flex gap-2 py-0.5">
          <span className="shrink-0 text-neutral-600">
            {new Date(event.created_at).toLocaleTimeString()}
          </span>
          <span className="shrink-0 text-neutral-500">[{event.node_name}]</span>
          <span className={EVENT_TYPE_COLOR[event.event_type] ?? "text-neutral-300"}>
            {event.message}
          </span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd frontend && npm test -- event-feed.test.tsx`
Expected: both tests PASS.

- [ ] **Step 9: Write the failing sub-researcher-tracks test**

Create `frontend/components/run/sub-researcher-tracks.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SubResearcherTracks } from "./sub-researcher-tracks";
import type { RunEvent } from "@/lib/types";

const events: RunEvent[] = [
  {
    node_name: "researcher", event_type: "started", message: "Researching sub-topic: pricing",
    payload: { sub_topic: "pricing" }, created_at: "2026-07-14T00:00:00Z",
  },
  {
    node_name: "researcher", event_type: "tool_call", message: "Found: Pricing report",
    payload: { sub_topic: "pricing", tool: "exa" }, created_at: "2026-07-14T00:00:10Z",
  },
  {
    node_name: "researcher", event_type: "started", message: "Researching sub-topic: competitors",
    payload: { sub_topic: "competitors" }, created_at: "2026-07-14T00:00:05Z",
  },
  {
    node_name: "compress_research", event_type: "completed", message: "Compressed findings for: pricing",
    payload: { sub_topic: "pricing" }, created_at: "2026-07-14T00:00:20Z",
  },
];

describe("SubResearcherTracks", () => {
  it("groups events into one card per sub-topic", () => {
    render(<SubResearcherTracks events={events} />);
    expect(screen.getByText("pricing")).toBeInTheDocument();
    expect(screen.getByText("competitors")).toBeInTheDocument();
    expect(screen.getByText("Found: Pricing report")).toBeInTheDocument();
  });

  it("marks a sub-topic done once its compress_research event completes", () => {
    render(<SubResearcherTracks events={events} />);
    const pricingCard = screen.getByText("pricing").closest("[data-subtopic]");
    expect(pricingCard).toHaveAttribute("data-done", "true");
    const competitorsCard = screen.getByText("competitors").closest("[data-subtopic]");
    expect(competitorsCard).toHaveAttribute("data-done", "false");
  });

  it("renders nothing when there are no researcher events yet", () => {
    const { container } = render(<SubResearcherTracks events={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 10: Run test to verify it fails**

Run: `cd frontend && npm test -- sub-researcher-tracks.test.tsx`
Expected: FAIL — `Cannot find module './sub-researcher-tracks'`.

- [ ] **Step 11: Implement the sub-researcher tracks**

Create `frontend/components/run/sub-researcher-tracks.tsx`:

```tsx
import { Card } from "@/components/ui/card";
import type { RunEvent } from "@/lib/types";

interface Track {
  subTopic: string;
  events: RunEvent[];
  done: boolean;
}

function groupBySubTopic(events: RunEvent[]): Track[] {
  const bySubTopic = new Map<string, RunEvent[]>();
  for (const event of events) {
    const subTopic = event.payload?.sub_topic;
    if (typeof subTopic !== "string") continue;
    const existing = bySubTopic.get(subTopic) ?? [];
    existing.push(event);
    bySubTopic.set(subTopic, existing);
  }

  return Array.from(bySubTopic.entries()).map(([subTopic, subEvents]) => ({
    subTopic,
    events: subEvents,
    done: subEvents.some(
      (e) => e.node_name === "compress_research" && e.event_type === "completed"
    ),
  }));
}

export function SubResearcherTracks({ events }: { events: RunEvent[] }) {
  const tracks = groupBySubTopic(events);

  if (tracks.length === 0) {
    return null;
  }

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {tracks.map((track) => (
        <Card key={track.subTopic} data-subtopic data-done={track.done} className="p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-medium">{track.subTopic}</h3>
            <span className="text-xs text-muted-foreground">{track.done ? "Done" : "Active"}</span>
          </div>
          <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
            {track.events.map((event, index) => (
              <li key={index}>{event.message}</li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}
```

- [ ] **Step 12: Run test to verify it passes**

Run: `cd frontend && npm test -- sub-researcher-tracks.test.tsx`
Expected: all 3 tests PASS.

- [ ] **Step 13: Implement the composed progress view**

Create `frontend/components/run/progress-view.tsx`:

```tsx
"use client";

import { useEffect, useMemo } from "react";

import { EventFeed } from "@/components/run/event-feed";
import { PhaseIndicator } from "@/components/run/phase-indicator";
import { SubResearcherTracks } from "@/components/run/sub-researcher-tracks";
import { useRunEvents } from "@/lib/use-run-events";
import type { NodeName, RunStatus } from "@/lib/types";

export function ProgressView({
  runId,
  initialStatus,
  onComplete,
}: {
  runId: string;
  initialStatus: RunStatus;
  onComplete: () => void;
}) {
  const { events, isConnected } = useRunEvents(runId, {
    enabled: initialStatus === "queued" || initialStatus === "running",
  });

  const currentPhase: NodeName | null = useMemo(() => {
    const last = [...events].reverse().find((e) => e.event_type !== "error");
    return last?.node_name ?? null;
  }, [events]);

  const isDone = useMemo(
    () =>
      events.some(
        (e) =>
          e.event_type === "error" ||
          (e.node_name === "idea_refine_generation" && e.event_type === "completed")
      ),
    [events]
  );

  useEffect(() => {
    if (isDone) {
      onComplete();
    }
  }, [isDone, onComplete]);

  const failed = events.some((e) => e.event_type === "error");

  return (
    <div className="flex flex-col gap-6">
      <PhaseIndicator currentPhase={currentPhase} />
      {failed && (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
          This run failed. See the log below for details.
        </p>
      )}
      <SubResearcherTracks events={events} />
      <EventFeed events={events} />
      {!isConnected && !isDone && (
        <p className="text-xs text-muted-foreground">Reconnecting…</p>
      )}
    </div>
  );
}
```

- [ ] **Step 14: Run the full test suite and linter**

Run: `cd frontend && npm test && npm run lint`
Expected: all tests pass; lint clean.

- [ ] **Step 15: Commit**

```bash
git add frontend/components/run/phase-indicator.tsx frontend/components/run/event-feed.tsx frontend/components/run/sub-researcher-tracks.tsx frontend/components/run/progress-view.tsx frontend/components/run/phase-indicator.test.tsx frontend/components/run/event-feed.test.tsx frontend/components/run/sub-researcher-tracks.test.tsx
git commit -m "feat(frontend): add Run Detail live progress view (phases, event feed, parallel tracks)"
```

---

### Task 6: Run Detail — reading view and page assembly

**Files:**
- Create: `frontend/components/run/report-view.tsx`
- Create: `frontend/components/run/sources-panel.tsx`
- Create: `frontend/components/run/idea-onepager.tsx`
- Create: `frontend/app/runs/[id]/page.tsx`
- Create: `frontend/app/runs/[id]/run-detail-client.tsx`
- Test: `frontend/components/run/report-view.test.tsx`
- Test: `frontend/components/run/idea-onepager.test.tsx`
- Test: `frontend/components/run/sources-panel.test.tsx`

**Interfaces:**
- Consumes: `RunDetail`, `SourceOut`, `IdeaOnePager` from Task 2's `lib/types.ts`; `getRun` from Task 2; `ProgressView` from Task 5.
- Produces: `ReportView({report: string})`, `SourcesPanel({sources: SourceOut[]})`, `IdeaOnePagerView({onepager: IdeaOnePager})`, `RunDetailClient({runId, initialRun})` (client component owning the progress↔reading state transition), the `/runs/[id]` page (server component fetching the initial `RunDetail` and rendering `RunDetailClient`).

- [ ] **Step 1: Write the failing report-view test**

Create `frontend/components/run/report-view.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportView } from "./report-view";

describe("ReportView", () => {
  it("renders markdown headings and links", () => {
    render(<ReportView report={"# Title\n\nSee [source](https://example.com) for details."} />);

    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "source" })).toHaveAttribute(
      "href", "https://example.com"
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- report-view.test.tsx`
Expected: FAIL — `Cannot find module './report-view'`.

- [ ] **Step 3: Implement the report view**

Create `frontend/components/run/report-view.tsx`:

```tsx
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function ReportView({ report }: { report: string }) {
  return (
    <article className="prose prose-neutral dark:prose-invert max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
    </article>
  );
}
```

Run: `cd frontend && npm install @tailwindcss/typography` and add the plugin to `frontend/app/globals.css`'s `@import`/`@plugin` directives (Tailwind v4 style, at the top of the file): `@plugin "@tailwindcss/typography";`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- report-view.test.tsx`
Expected: PASS.

- [ ] **Step 5: Write the failing idea-onepager test**

Create `frontend/components/run/idea-onepager.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IdeaOnePagerView } from "./idea-onepager";
import type { IdeaOnePager } from "@/lib/types";

const onepager: IdeaOnePager = {
  problem_statement: "Users lose track of notes over time.",
  recommended_direction: "A retention-focused review workflow.",
  key_assumptions: ["Users want spaced review"],
  mvp_scope: ["Weekly digest email"],
  not_doing: ["Real-time collaboration"],
  open_questions: ["What's the willingness to pay?"],
};

describe("IdeaOnePagerView", () => {
  it("renders every section", () => {
    render(<IdeaOnePagerView onepager={onepager} />);
    expect(screen.getByText(onepager.problem_statement)).toBeInTheDocument();
    expect(screen.getByText(onepager.recommended_direction)).toBeInTheDocument();
    expect(screen.getByText("Users want spaced review")).toBeInTheDocument();
    expect(screen.getByText("Weekly digest email")).toBeInTheDocument();
    expect(screen.getByText("Real-time collaboration")).toBeInTheDocument();
    expect(screen.getByText("What's the willingness to pay?")).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd frontend && npm test -- idea-onepager.test.tsx`
Expected: FAIL — `Cannot find module './idea-onepager'`.

- [ ] **Step 7: Implement the idea one-pager**

Create `frontend/components/run/idea-onepager.tsx`:

```tsx
import { Card } from "@/components/ui/card";
import type { IdeaOnePager } from "@/lib/types";

function ChecklistSection({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-medium">{title}</h3>
      <ul className="flex flex-col gap-1 text-sm text-muted-foreground">
        {items.map((item, index) => (
          <li key={index} className="flex gap-2">
            <span>•</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function IdeaOnePagerView({ onepager }: { onepager: IdeaOnePager }) {
  return (
    <Card className="flex flex-col gap-6 p-6">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Idea One-Pager</h2>
      </div>
      <div>
        <h3 className="mb-1 text-sm font-medium">Problem statement</h3>
        <p className="text-sm text-muted-foreground">{onepager.problem_statement}</p>
      </div>
      <div>
        <h3 className="mb-1 text-sm font-medium">Recommended direction</h3>
        <p className="text-sm text-muted-foreground">{onepager.recommended_direction}</p>
      </div>
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <ChecklistSection title="Key assumptions to validate" items={onepager.key_assumptions} />
        <ChecklistSection title="MVP scope" items={onepager.mvp_scope} />
        <ChecklistSection title="Not doing" items={onepager.not_doing} />
        <ChecklistSection title="Open questions" items={onepager.open_questions} />
      </div>
    </Card>
  );
}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd frontend && npm test -- idea-onepager.test.tsx`
Expected: PASS.

- [ ] **Step 9: Write the failing sources-panel test**

Create `frontend/components/run/sources-panel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourcesPanel } from "./sources-panel";
import type { SourceOut } from "@/lib/types";

const sources: SourceOut[] = [
  { id: "1", tool_name: "exa", url: "https://a.com", title: "A", snippet: "a", retrieved_at: "2026-07-14T00:00:00Z" },
  { id: "2", tool_name: "reddit", url: "https://b.com", title: "B", snippet: "b", retrieved_at: "2026-07-14T00:00:00Z" },
];

describe("SourcesPanel", () => {
  it("groups sources by tool", () => {
    render(<SourcesPanel sources={sources} />);
    expect(screen.getByText("exa")).toBeInTheDocument();
    expect(screen.getByText("reddit")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "A" })).toHaveAttribute("href", "https://a.com");
  });

  it("shows an empty state with no sources", () => {
    render(<SourcesPanel sources={[]} />);
    expect(screen.getByText(/no sources/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 10: Run test to verify it fails**

Run: `cd frontend && npm test -- sources-panel.test.tsx`
Expected: FAIL — `Cannot find module './sources-panel'`.

- [ ] **Step 11: Implement the sources panel**

Create `frontend/components/run/sources-panel.tsx`:

```tsx
import type { SourceOut } from "@/lib/types";

function groupByTool(sources: SourceOut[]): Record<string, SourceOut[]> {
  return sources.reduce<Record<string, SourceOut[]>>((groups, source) => {
    (groups[source.tool_name] ??= []).push(source);
    return groups;
  }, {});
}

export function SourcesPanel({ sources }: { sources: SourceOut[] }) {
  if (sources.length === 0) {
    return <p className="text-sm text-muted-foreground">No sources recorded for this run.</p>;
  }

  const grouped = groupByTool(sources);

  return (
    <div className="flex flex-col gap-6">
      {Object.entries(grouped).map(([tool, toolSources]) => (
        <div key={tool}>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {tool}
          </h3>
          <ul className="flex flex-col gap-3">
            {toolSources.map((source) => (
              <li key={source.id}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm font-medium hover:underline"
                >
                  {source.title}
                </a>
                <p className="text-xs text-muted-foreground">{source.snippet}</p>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 12: Run test to verify it passes**

Run: `cd frontend && npm test -- sources-panel.test.tsx`
Expected: both tests PASS.

- [ ] **Step 13: Implement the client-side view-switching component**

Create `frontend/app/runs/[id]/run-detail-client.tsx`:

```tsx
"use client";

import { useCallback, useState } from "react";

import { IdeaOnePagerView } from "@/components/run/idea-onepager";
import { ProgressView } from "@/components/run/progress-view";
import { ReportView } from "@/components/run/report-view";
import { SourcesPanel } from "@/components/run/sources-panel";
import { getRun } from "@/lib/api";
import type { RunDetail } from "@/lib/types";

export function RunDetailClient({ initialRun }: { initialRun: RunDetail }) {
  const [run, setRun] = useState(initialRun);

  const refetch = useCallback(async () => {
    const updated = await getRun(initialRun.id);
    setRun(updated);
  }, [initialRun.id]);

  const isTerminal = run.status === "completed" || run.status === "failed";

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{run.topic}</h1>
        {run.constraints && <p className="text-sm text-muted-foreground">{run.constraints}</p>}
      </div>

      {!isTerminal && (
        <ProgressView runId={run.id} initialStatus={run.status} onComplete={refetch} />
      )}

      {run.status === "failed" && (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {run.error ?? "This run failed."}
        </p>
      )}

      {run.status === "completed" && (
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="flex flex-col gap-10">
            {run.final_report && <ReportView report={run.final_report} />}
            {run.idea_onepager && <IdeaOnePagerView onepager={run.idea_onepager} />}
          </div>
          <aside>
            <h2 className="mb-4 text-sm font-medium text-muted-foreground">Sources</h2>
            <SourcesPanel sources={run.sources} />
          </aside>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 14: Implement the page**

Create `frontend/app/runs/[id]/page.tsx`:

```tsx
import { notFound } from "next/navigation";

import { RunDetailClient } from "./run-detail-client";
import { getRun } from "@/lib/api";

export default async function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let run;
  try {
    run = await getRun(id);
  } catch {
    notFound();
  }

  return <RunDetailClient initialRun={run} />;
}
```

- [ ] **Step 15: Run the full test suite and linter**

Run: `cd frontend && npm test && npm run lint`
Expected: all tests pass; lint clean.

- [ ] **Step 16: Commit**

```bash
git add frontend/components/run/report-view.tsx frontend/components/run/sources-panel.tsx frontend/components/run/idea-onepager.tsx frontend/app/runs/[id] frontend/components/run/report-view.test.tsx frontend/components/run/idea-onepager.test.tsx frontend/components/run/sources-panel.test.tsx frontend/app/globals.css frontend/package.json frontend/package-lock.json
git commit -m "feat(frontend): add Run Detail reading view (report, idea one-pager, sources) and page assembly"
```

---

### Task 7: Export buttons (PDF/XLSX)

**Files:**
- Create: `frontend/components/run/export-buttons.tsx`
- Modify: `frontend/app/runs/[id]/run-detail-client.tsx`
- Test: `frontend/components/run/export-buttons.test.tsx`

**Interfaces:**
- Consumes: `createExport`, `getExportStatus` from Task 2.
- Produces: `ExportButtons({runId: string})` (client component: "Export PDF" / "Export Excel" buttons, each triggers `createExport`, then polls `getExportStatus` every 2s until a `redirectUrl` is returned, then navigates to it to trigger the browser download) — mounted into `RunDetailClient` from Task 6 when `run.status === "completed"`.

- [ ] **Step 1: Write the failing test**

Create `frontend/components/run/export-buttons.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExportButtons } from "./export-buttons";

const originalLocation = window.location;

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  // @ts-expect-error -- replacing window.location for assertions on navigation
  delete window.location;
  // @ts-expect-error -- minimal stub sufficient for this test
  window.location = { ...originalLocation, href: "" };
});

afterEach(() => {
  vi.useRealTimers();
  window.location = originalLocation;
  vi.restoreAllMocks();
});

describe("ExportButtons", () => {
  it("starts a PDF export, polls, and navigates to the download URL when ready", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ export_id: "exp-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "generating" }), { status: 202 }))
      .mockResolvedValueOnce(
        new Response(null, { status: 303, headers: { Location: "https://minio.local/report.pdf" } })
      );

    render(<ExportButtons runId="run-1" />);
    await user.click(screen.getByRole("button", { name: /export pdf/i }));

    expect(await screen.findByText(/generating/i)).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(2100);
    await vi.advanceTimersByTimeAsync(2100);

    expect(window.location.href).toBe("https://minio.local/report.pdf");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- export-buttons.test.tsx`
Expected: FAIL — `Cannot find module './export-buttons'`.

- [ ] **Step 3: Implement the export buttons**

Create `frontend/components/run/export-buttons.tsx`:

```tsx
"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { createExport, getExportStatus } from "@/lib/api";

type ExportState = "idle" | "generating" | "error";

function useExport(runId: string, format: "pdf" | "xlsx") {
  const [state, setState] = useState<ExportState>("idle");

  async function start() {
    setState("generating");
    try {
      await createExport(runId, format);
      poll();
    } catch {
      setState("error");
    }
  }

  function poll() {
    const interval = setInterval(async () => {
      try {
        const result = await getExportStatus(runId, format);
        if ("redirectUrl" in result) {
          clearInterval(interval);
          setState("idle");
          window.location.href = result.redirectUrl;
        }
      } catch {
        clearInterval(interval);
        setState("error");
      }
    }, 2000);
  }

  return { state, start };
}

export function ExportButtons({ runId }: { runId: string }) {
  const pdf = useExport(runId, "pdf");
  const xlsx = useExport(runId, "xlsx");

  return (
    <div className="flex items-center gap-3">
      <Button variant="outline" onClick={pdf.start} disabled={pdf.state === "generating"}>
        {pdf.state === "generating" ? "Generating PDF…" : "Export PDF"}
      </Button>
      <Button variant="outline" onClick={xlsx.start} disabled={xlsx.state === "generating"}>
        {xlsx.state === "generating" ? "Generating Excel…" : "Export Excel"}
      </Button>
      {(pdf.state === "error" || xlsx.state === "error") && (
        <span className="text-xs text-destructive">Export failed — try again.</span>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- export-buttons.test.tsx`
Expected: PASS.

- [ ] **Step 5: Mount the export buttons in the completed-run view**

In `frontend/app/runs/[id]/run-detail-client.tsx`, add the import:

```tsx
import { ExportButtons } from "@/components/run/export-buttons";
```

And inside the `run.status === "completed"` block, add `<ExportButtons runId={run.id} />` directly above the two-column `<div className="grid ...">`.

- [ ] **Step 6: Run the full test suite and linter**

Run: `cd frontend && npm test && npm run lint`
Expected: all tests pass; lint clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/run/export-buttons.tsx frontend/components/run/export-buttons.test.tsx frontend/app/runs/[id]/run-detail-client.tsx
git commit -m "feat(frontend): add PDF/Excel export buttons with polling"
```

---

## Post-Plan Manual Verification

With Plan 2's backend fully implemented and running (`docker compose up -d postgres redis minio backend worker`, migrations applied):

```bash
cd frontend
cp .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`, submit a topic on the New Run page, confirm the redirect to `/runs/{id}` shows the live progress view (phase indicator advancing, event feed scrolling, parallel sub-researcher cards appearing during the research phase), confirm it automatically switches to the reading view once the run completes (this takes several minutes — it's a real LLM+search-backed run), confirm the report/idea one-pager/sources render correctly, and confirm both "Export PDF" and "Export Excel" produce a downloadable file. Then visit `/runs` and confirm the new run appears in history.

Toggle the theme switcher and confirm both light and dark mode look correct on all three screens, with the event feed panel staying console-dark in both.