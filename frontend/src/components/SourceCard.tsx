import type { Source } from "../types/api";
import { pct, score } from "../utils/format";
import { useSourceDetails } from "./Citation";
import { Icon } from "./Icon";

export function SourceCard({ source, cited }: { source: Source; cited: boolean }) {
  const { open } = useSourceDetails();
  const kb = source.source_type === "knowledge_base";
  const dup = (source.extra as { duplicate_count?: number }).duplicate_count;
  return (
    <button type="button" className={`source-card ${cited ? "cited" : ""}`} onClick={() => open(source.source_id)}>
      <div className="source-head">
        <span className={`badge ${kb ? "badge-brown" : "badge-yellow"}`}><Icon name={kb ? "book" : "folder"} size={12} />{kb ? source.source_id : `Ticket ${source.source_id}`}</span>
        <span className="badge badge-neutral">{kb ? "Help article" : "Past case"}</span>
        {cited && <span className="badge badge-known"><Icon name="link" size={12} />Cited</span>}
        <span className="spacer" />
        <span className="tiny muted">Match <b>{pct(source.final_score)}</b></span>
      </div>
      <div className="source-title">{source.title}</div>
      <p className="source-excerpt clamp-2">{source.excerpt}</p>
      {dup && dup > 1 ? <div className="tiny muted" style={{ marginBottom: 8 }}>+{dup - 1} similar past cases</div> : null}
      <details className="details" onClick={(e) => e.stopPropagation()}>
        <summary>Scores</summary>
        <div className="details-body score-row">
          <span className="score-pill">Meaning <b>{score(source.semantic_score)}</b></span>
          <span className="score-pill">Keywords <b>{score(source.keyword_score)}</b></span>
          <span className="score-pill">Re-rank <b>{score(source.reranker_score)}</b></span>
          <span className="score-pill final">Overall <b>{score(source.final_score)}</b></span>
        </div>
      </details>
    </button>
  );
}
