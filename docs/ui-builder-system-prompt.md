# System Prompt — Deep Research Market Agent Frontend

Paste this whole document into your AI UI builder (v0, Lovable, Bolt, etc.) as the
project brief / system prompt. It describes the product, the exact data it will
receive, the screens to build, and the visual direction.

---

## 1. What we're building

**Deep Research Market Agent** is a single-operator, internal web tool. A user
types in a market or topic (e.g. "AI note-taking apps"), and an autonomous
research agent:

1. Turns that topic into a structured research brief.
2. Runs multiple rounds of parallel research across the web, recent news, and
   community discussion (Reddit) — a "lead researcher" delegates sub-topics to
   several "sub-researchers" running concurrently.
3. Compresses all findings into a long-form **markdown research report** with
   citations.
4. Runs a second, headless pass over that report — the same divergent →
   convergent thinking as a product ideation exercise — to produce an
   **idea one-pager**: a recommended product/business direction grounded in
   the research, with assumptions to validate, MVP scope, and a "not doing" list.
5. Lets the user export the report + one-pager to PDF or Excel.

The whole thing runs as one long asynchronous job (typically minutes, not
seconds) with **live progress streaming** — the UI's job is to make that wait
feel transparent and trustworthy, then present the output beautifully.

There is no login/auth and no multi-user concept — build it as a single
operator's internal tool. Do not add sign-in flows.

---

## 2. Screens to build

### 2a. New Run (home page, `/`)
- A focused, centered input: topic (required, short text) + optional
  "constraints" (free text, collapsible/advanced — e.g. "focus on B2B",
  "US market only").
- Primary CTA: "Start Research" → `POST /runs` → redirect to `/runs/{id}`.
- A secondary link/list to recent runs (last 5) so this page doubles as a
  quick launcher, with a link to the full History page.
- This is the highest-polish, lowest-density screen — set the tone for the
  product.

### 2b. Run Detail (`/runs/[id]`)
This screen has two states that morph into each other, not two separate pages:

**While running** — a live progress view:
- Current phase indicator (brief → research → compress → report → ideation),
  with the currently-active phase highlighted.
- A live event feed: each event has a node name, a short human-readable
  message, and a timestamp (see §4 event shape). This should read like an
  agent console/activity log — most recent at top or bottom, auto-scrolling,
  clearly distinguishing "started X" / "using tool Y" / "completed X" events.
- When research is delegating to parallel sub-researchers, visually show
  concurrent sub-topics as parallel tracks/cards, each ticking through its own
  tool calls (exa, tavily, newsapi, reddit) — this is the moment users are
  most curious what the agent is "doing right now."
- Graceful failure state if `status` becomes `failed`: show the error and the
  partial event log (don't hide progress already made).

**Once complete** — a reading view:
- The final markdown report, rendered with good typography (headings, lists,
  blockquotes, inline citation links out to source URLs) — this should feel
  like reading a well-formatted long-form article/PDF, not a chat bubble.
- A **Sources** panel/sidebar: every citation surfaced during research,
  grouped or filterable by tool (Exa / Tavily / NewsAPI / Reddit), each a
  title + link + snippet.
- The **Idea One-Pager** as a distinct, visually separated section below or
  beside the report — structured, scannable (not just another wall of text):
  problem statement, recommended direction, key assumptions to validate
  (checklist-style), MVP scope, "not doing" list, open questions.
- Export actions: "Export PDF" / "Export Excel" buttons that trigger
  `POST /runs/{id}/export`, then poll and download when ready (show a
  generating → ready state transition, not just a spinner with no feedback).

### 2c. History (`/runs`)
- Paginated table/list of past runs: topic, status (queued/running/completed/
  failed — needs distinct visual treatment per status), created date, link to
  detail page.
- Simple, dense, scannable — this is a utility screen, not a showcase one.

---

## 3. Design direction

Build with **Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui**.
Use shadcn's theming tokens (CSS variables) so colors/radius/fonts are easy to
swap later — don't hardcode raw hex values in components.

The three screens have different jobs, so let each lean into its own register
while sharing one design system (same tokens, spacing scale, and components):

- **New Run** — clean, minimal, dashboard/SaaS feel (think Linear/Vercel):
  generous whitespace, one clear primary action.
- **Run Detail (live progress)** — agent-console feel: monospace or
  semi-monospace accents for the event feed, subtle motion (fade/slide-in
  per new event, animated "active" state on the current phase), dark-mode-
  friendly log aesthetic even in light mode (e.g. a contained dark panel for
  the feed is fine even if the rest of the page is light).
- **Run Detail (report) / idea one-pager** — editorial/reading feel:
  article-width max content column, strong typographic hierarchy, comfortable
  line-height — optimized for reading, not scanning.
- **History** — dense dashboard table.

Support both light and dark mode. Ship a default neutral palette (the tool's
actual brand isn't decided yet) but make it trivial to re-theme via the
shadcn CSS variables — treat colors as placeholders, not a final identity.

Sidebar or top nav (your call) with: New Run, History. Keep global chrome
minimal so it doesn't compete with the report-reading experience.

---

## 4. Data & API contract (backend already defined — build the frontend to match)

Base: FastAPI backend, JSON over REST + one SSE stream. Backend is not yet
built in some cases — build the frontend against this contract with mocked/
fixture data, structured so swapping in real fetch calls is a small change.

**`POST /runs`**
Request: `{ topic: string, constraints?: string }`
Response: `201 { run_id: string }`

**`GET /runs`** — paginated history
Response: `{ runs: Array<{ id, topic, status, created_at, updated_at }>, ... pagination }`

**`GET /runs/{id}`** — full run detail
```ts
{
  id: string
  topic: string
  constraints?: string
  status: "queued" | "running" | "completed" | "failed"
  research_brief?: string        // markdown
  final_report?: string          // markdown, present once far enough along
  idea_onepager?: {
    problem_statement: string
    recommended_direction: string
    key_assumptions: string[]
    mvp_scope: string[]
    not_doing: string[]
    open_questions: string[]
  }
  sources: Array<{
    id: string
    tool_name: "exa" | "tavily" | "newsapi" | "reddit"
    url: string
    title: string
    snippet: string
    retrieved_at: string
  }>
  error?: string
  created_at: string
  updated_at: string
}
```

**`GET /runs/{id}/events`** (Server-Sent Events) — replays past events then
live-tails new ones until the run reaches a terminal status. Each event:
```ts
{
  node_name:
    | "write_research_brief"
    | "supervisor"
    | "researcher"          // one per parallel sub-topic; include a sub-topic label in payload
    | "compress_research"
    | "final_report_generation"
    | "idea_refine_generation"  // has 3 sub-phases: understand_expand, evaluate_converge, sharpen_ship
  event_type: "started" | "tool_call" | "progress" | "completed" | "error"
  message: string             // human-readable, e.g. "Searching Reddit for \"AI note-taking retention\""
  payload?: Record<string, unknown>  // e.g. { tool: "reddit_search", sub_topic: "..." }
  created_at: string
}
```
Build the live progress UI to consume a stream of these — group by
`node_name`, treat `researcher` events as potentially concurrent (multiple
active sub-topics at once), and treat reaching `final_report_generation` /
`idea_refine_generation` `completed` as the signal to switch Run Detail from
progress view to reading view.

**`POST /runs/{id}/export`**
Request: `{ format: "pdf" | "xlsx" }`
Response: `{ export_id: string }` — export status is `generating` initially.

**`GET /runs/{id}/export/{format}`**
Returns `303` redirect to a download URL once ready, or `202` with
`{ status: "generating" }` while still processing — poll this endpoint after
triggering an export.

---

## 5. Explicitly out of scope

- No authentication / user accounts / multi-tenancy.
- No editing or resuming a run mid-flight — a run is start-to-finish or
  restart-from-scratch.
- No real-time collaborative editing of the report or one-pager.

---

## 6. What "done" looks like for the first UI pass

A working New Run → live Run Detail (progress → report) → History loop,
against mocked data matching the shapes in §4, with the visual register
described in §3 for each screen, built in Next.js + Tailwind + shadcn/ui with
swappable theme tokens.
