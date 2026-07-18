export type RecentSession = {
  id: string;
  title: string;
  timeAgo: string;
};

export const RECENT_SESSIONS: RecentSession[] = [
  { id: "ev-battery", title: "EV battery supply chain, APAC", timeAgo: "Yesterday" },
  { id: "fintech-teardown", title: "Fintech competitor teardown", timeAgo: "3 days ago" },
  { id: "plant-protein", title: "Plant-based protein consumer trends", timeAgo: "1 week ago" },
  { id: "ai-coding", title: "AI coding assistants market sizing", timeAgo: "2 weeks ago" },
];

export const SUGGESTIONS: string[] = [
  "Competitive landscape for enterprise SaaS in fintech",
  "Consumer trends in plant-based foods, US market",
  "Market sizing for AI coding assistants",
];

export const CLARIFY_CHIPS: string[] = [
  "Region: Global",
  "Region: North America",
  "Focus: competitors",
  "Focus: pricing",
  "Timeframe: last 12 months",
];

export type ProgressStep = {
  title: string;
  detail?: string;
};

export const PROGRESS_STEPS: ProgressStep[] = [
  { title: "Planning research approach" },
  {
    title: "Scanning market sources",
    detail:
      "Querying industry reports, financial filings, news archives, and analyst commentary across roughly thirty candidate sources, filtering for recency and credibility.",
  },
  { title: "Analyzing competitive signals" },
  { title: "Cross-referencing data points" },
  { title: "Synthesizing findings" },
];

export type Source = {
  domain: string;
  letter: string;
  blurb: string;
};

export const SOURCES: Source[] = [
  { domain: "reuters.com", letter: "R", blurb: "Global market outlook report 2026" },
  { domain: "statista.com", letter: "S", blurb: "Industry revenue forecasts" },
  { domain: "mckinsey.com", letter: "M", blurb: "Competitive dynamics and M&A trends" },
  { domain: "bloomberg.com", letter: "B", blurb: "Quarterly earnings commentary" },
  { domain: "crunchbase.com", letter: "C", blurb: "Funding rounds and new entrants" },
  { domain: "gartner.com", letter: "G", blurb: "Market share estimates" },
  { domain: "ft.com", letter: "F", blurb: "Regulatory developments overview" },
  { domain: "pitchbook.com", letter: "P", blurb: "Private market valuations" },
  { domain: "techcrunch.com", letter: "T", blurb: "Product launches and positioning" },
  { domain: "linkedin.com", letter: "L", blurb: "Hiring trends and org signals" },
  { domain: "sec.gov", letter: "S", blurb: "10-K filings and risk factors" },
  { domain: "similarweb.com", letter: "S", blurb: "Traffic and demand indicators" },
];

export type StatCard = {
  label: string;
  value: string;
  sub: string;
};

export const STAT_CARDS: StatCard[] = [
  { label: "ESTIMATED MARKET SIZE", value: "$4.2B", sub: "+9.8% YoY" },
  { label: "ACTIVE COMPETITORS TRACKED", value: "27", sub: "+4 new entrants" },
  { label: "SOURCES REVIEWED", value: "24", sub: "high confidence" },
];

export type ReportSection = {
  heading: string;
  body: string;
};

export const REPORT_SECTIONS: ReportSection[] = [
  {
    heading: "Market Overview",
    body: "The market has grown steadily as buyers consolidate spend and demand matures. Sizing points to a multi-billion-dollar opportunity, expanding at a high single-digit to low double-digit rate year over year, driven by broadening adoption across regions.",
  },
  {
    heading: "Competitive Landscape",
    body: "A handful of players hold the majority of tracked share. Established leaders compete on breadth and enterprise trust, while faster-growing challengers are gaining ground on pricing, speed of implementation, and focus on underserved segments.",
  },
  {
    heading: "Key Risks & Opportunities",
    body: "Pricing pressure from new entrants is compressing margins industry-wide. The clearest opportunity is expansion into currently underserved regions and segments, where demand signals outpace existing supply.",
  },
];

export type TableRow = {
  metric: string;
  value: string;
  source: string;
};

export const TABLE_ROWS: TableRow[] = [
  { metric: "Estimated market size", value: "$4.2B", source: "statista.com" },
  { metric: "YoY growth rate", value: "9.8%", source: "mckinsey.com" },
  { metric: "Active competitors tracked", value: "27", source: "crunchbase.com" },
  { metric: "New entrants (last 12mo)", value: "4", source: "pitchbook.com" },
  { metric: "Top competitor share", value: "31%", source: "gartner.com" },
  { metric: "Median contract value", value: "$86K", source: "bloomberg.com" },
  { metric: "Sources reviewed", value: "24", source: "internal" },
];
