import type { KnowledgeArticle } from "../types/api";

export interface ParsedArticle {
  symptoms: string;
  steps: string[];
}

/**
 * Splits a knowledge-base article into the parts customers should see: the "Customer steps" when the article has
 * them (plain wording for customers), otherwise the resolution steps. "Also asked as", "Escalate when", "Caution"
 * and "Source note" lines are internal and left out.
 */
export function parseArticle(content: string): ParsedArticle {
  const parsed: ParsedArticle = { symptoms: "", steps: [] };
  const agentSteps: string[] = [];
  const customerSteps: string[] = [];
  let sectionName = "resolution steps";
  for (const raw of content.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const section = line.match(/^(Symptoms|Also asked as|Resolution steps|Customer steps|Escalate when|Caution|Source note):\s*(.*)$/i);
    if (section) {
      sectionName = section[1].toLowerCase();
      if (sectionName === "symptoms") parsed.symptoms = section[2];
      continue;
    }
    const step = line.match(/^\d+[.)]\s+(.*)$/);
    if (step) (sectionName === "customer steps" ? customerSteps : agentSteps).push(step[1]);
  }
  parsed.steps = customerSteps.length ? customerSteps : agentSteps;
  return parsed;
}

/** "KB-031: Evening broadband drops" -> "Evening broadband drops" (customers never see internal IDs). */
export const cleanTitle = (title: string) => title.replace(/^KB-\d+:\s*/, "").replace(/\s*\(draft[^)]*\)\s*$/i, "");

export const isGeneral = (a: KnowledgeArticle) => a.source === "synthetic_demo_kb_general";

const WORD = /[a-z0-9]+/g;
const STOP = new Set(["my", "the", "a", "an", "is", "are", "i", "to", "of", "on", "in", "and", "or", "it", "not", "how", "do", "can", "what", "with", "for", "me"]);
const words = (text: string) => (text.toLowerCase().match(WORD) ?? []).filter((w) => !STOP.has(w));
const stem = (w: string) => w.replace(/(ing|ed|es|s)$/, "");

/** Simple word-overlap search: title matches count more than body matches. */
export function searchArticles(articles: KnowledgeArticle[], query: string, limit = 6): KnowledgeArticle[] {
  const terms = [...new Set(words(query).map(stem))];
  if (!terms.length) return [];
  return articles
    .map((a) => {
      const title = new Set(words(cleanTitle(a.title)).map(stem));
      const body = new Set(words(a.content).map(stem));
      const score = terms.reduce((sum, t) => sum + (title.has(t) ? 3 : body.has(t) ? 1 : 0), 0) - (isGeneral(a) ? 0.5 : 0);
      return { a, score, hits: terms.filter((t) => title.has(t) || body.has(t)).length };
    })
    .filter((r) => r.hits >= Math.min(2, terms.length))
    .sort((x, y) => y.score - x.score)
    .slice(0, limit)
    .map((r) => r.a);
}

export const formatDate = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
};
