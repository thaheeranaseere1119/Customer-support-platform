import type { Analysis } from "../types/api";
import { humanize, pct } from "../utils/format";
import { IntentBadge, SentimentBadge, SeverityBadge } from "./Badges";
import { EntityList } from "./EntityList";
import { Icon } from "./Icon";

export function AnalysisCard({ analysis }: { analysis: Analysis }) {
  return (
    <section className="card" aria-labelledby="analysis-title">
      <div className="card-header">
        <div><h3 id="analysis-title" className="card-title">Issue summary</h3></div>
        <div className="row">
          {analysis.used_memory && <span className="badge badge-info"><Icon name="clock" size={12} />Memory applied</span>}
          <span className="badge badge-neutral" title="How the issue type was determined">{humanize(analysis.classification_method)}</span>
        </div>
      </div>
      <div className="analysis-grid">
        <div className="analysis-item"><div className="eyebrow">Issue type</div><div className="value">{analysis.intent_display}</div>
          <div className="row" style={{ marginTop: 6 }}><IntentBadge intent={analysis.intent} display={analysis.intent === "unknown" ? "Unknown" : `${pct(analysis.intent_confidence)} confidence`} /></div></div>
        <div className="analysis-item"><div className="eyebrow">Category</div><div className="value">{analysis.category}</div>
          <div className="tiny muted">{analysis.subcategory ? `${analysis.subcategory} · ` : ""}{analysis.domain_category}</div></div>
        <div className="analysis-item"><div className="eyebrow">Product</div><div className="value">{humanize(analysis.product)}</div></div>
        <div className="analysis-item"><div className="eyebrow">Severity</div><div className="value"><SeverityBadge severity={analysis.severity} /></div>
          <div className="tiny muted" style={{ marginTop: 6 }}>{analysis.severity_reasons.join("; ")}</div></div>
        <div className="analysis-item"><div className="eyebrow">Sentiment</div><div className="value"><SentimentBadge sentiment={analysis.sentiment} /></div></div>
        <div className="analysis-item"><div className="eyebrow">Details picked up</div><div className="value">{analysis.entities.length + analysis.memory_entities.length}</div></div>
      </div>
      <div className="section-gap"><div className="eyebrow" style={{ marginBottom: 8 }}>Details</div>
        <EntityList entities={analysis.entities} memory={analysis.memory_entities} /></div>
    </section>
  );
}
