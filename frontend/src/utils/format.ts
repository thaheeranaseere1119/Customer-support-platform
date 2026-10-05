import type { EvidenceStatus } from "../types/api";

export const pct = (value: number | null | undefined, digits = 0): string =>
  value === null || value === undefined || Number.isNaN(value) ? "—" : `${(value * 100).toFixed(digits)}%`;

export const num = (value: number | null | undefined): string =>
  value === null || value === undefined ? "—" : new Intl.NumberFormat("en").format(value);

export const score = (value: number | null | undefined): string =>
  value === null || value === undefined ? "n/a" : value.toFixed(2);

export const humanize = (value: string | null | undefined): string =>
  (value || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const timeAgo = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const date = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return date.toLocaleDateString();
};

export const statusLabel: Record<EvidenceStatus, string> = { known: "High confidence", uncertain: "Medium confidence", unknown: "Low confidence" };

export const caseStatusLabel = (status: string): string =>
  ({
    awaiting_feedback: "Awaiting feedback", resolved: "Resolved", candidate_submitted: "Candidate submitted",
    needs_more_info: "Needs more info", retry_pending: "Retry pending", escalated: "Escalated",
  })[status] ?? humanize(status);

export const CITATION_PATTERN = /\[([A-Za-z0-9][A-Za-z0-9_\-:.]{1,60})\]/g;

/** Split text into plain segments and citation IDs (rendered as components, never as HTML). */
export function splitCitations(text: string): ({ kind: "text"; value: string } | { kind: "cite"; id: string })[] {
  const parts: ({ kind: "text"; value: string } | { kind: "cite"; id: string })[] = [];
  let last = 0;
  for (const match of text.matchAll(CITATION_PATTERN)) {
    const index = match.index ?? 0;
    if (index > last) parts.push({ kind: "text", value: text.slice(last, index) });
    parts.push({ kind: "cite", id: match[1] });
    last = index + match[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", value: text.slice(last) });
  return parts;
}

export const linesToList = (value: string): string[] => value.split("\n").map((l) => l.trim()).filter(Boolean);

/** Where a review-queue item came from, in plain words. */
export const ORIGIN_LABEL: Record<string, string> = {
  live_feedback: "Customer confirmed a fix",
  kb_match: "New question, answered by an article",
  agent_resolved: "Solved by an agent",
  dataset: "Past tickets",
  demo_seed: "Sample data",
};
export const LIVE_ORIGINS = ["live_feedback", "kb_match", "agent_resolved"];
