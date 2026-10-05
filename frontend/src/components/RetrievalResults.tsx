import { useState } from "react";
import type { Retrieval } from "../types/api";
import { humanize } from "../utils/format";
import { EvidenceScore } from "./EvidenceScore";
import { SourceCard } from "./SourceCard";

type Tab = "all" | "historical_ticket" | "knowledge_base";

export function RetrievalResults({ retrieval, citedIds }: { retrieval: Retrieval; citedIds: Set<string> }) {
  const [tab, setTab] = useState<Tab>("all");
  const sources = retrieval.sources.filter((s) => tab === "all" || s.source_type === tab);
  const count = (t: Tab) => retrieval.sources.filter((s) => t === "all" || s.source_type === t).length;
  return (
    <section className="card" aria-labelledby="evidence-title">
      <div className="card-header">
        <div><h3 id="evidence-title" className="card-title">Sources the assistant found</h3></div>
      </div>
      <EvidenceScore evidence={retrieval.evidence} />
      <details className="details section-gap">
        <summary>How the sources were found</summary>
        <div className="details-body row tiny muted">
          <span className="badge badge-neutral">{retrieval.semantic_used ? humanize(retrieval.vector_backend) : "Keyword only"}</span>
          <span className="badge badge-neutral">{retrieval.keyword_used ? "Keyword search on" : "Keyword search off"}</span>
          <span className="badge badge-neutral">{retrieval.reranker_method === "cross_encoder" ? "Re-ranked" : "Not re-ranked"}</span>
          <span>{retrieval.candidates_considered} candidates checked in {Math.round(retrieval.latency_ms)} ms</span>
        </div>
      </details>
      {retrieval.degraded_reasons.length > 0 && (
        <div className="warning-box section-gap" role="note">Search ran with reduced features: {retrieval.degraded_reasons.map(humanize).join(", ")}.</div>
      )}
      {retrieval.excluded_source_ids.length > 0 && (
        <div className="followup-box section-gap">This attempt skipped sources used before: {retrieval.excluded_source_ids.join(", ")}</div>
      )}
      <div className="row section-gap" style={{ marginBottom: 12 }}>
        <span className="eyebrow">Matching sources</span><span className="spacer" />
        <div className="tabs" role="tablist" aria-label="Source type">
          {(["all", "historical_ticket", "knowledge_base"] as Tab[]).map((t) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
              {t === "all" ? "All" : t === "historical_ticket" ? "Past cases" : "Help articles"} ({count(t)})
            </button>
          ))}
        </div>
      </div>
      <div className="stack-sm">
        {sources.map((s) => <SourceCard key={s.source_id} source={s} cited={citedIds.has(s.source_id)} />)}
        {sources.length === 0 && <p className="small muted">No matching sources for this complaint.</p>}
      </div>
    </section>
  );
}
