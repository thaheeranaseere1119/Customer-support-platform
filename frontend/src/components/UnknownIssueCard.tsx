import type { ResolveResponse } from "../types/api";
import { score } from "../utils/format";
import { Icon } from "./Icon";

export function UnknownIssueCard({ unknown }: { unknown: NonNullable<ResolveResponse["unknown_issue"]> }) {
  return (
    <section className="unknown-card" role="alert" aria-labelledby="unknown-title">
      <div className="row"><Icon name="radar" size={18} /><span className="eyebrow">New issue</span></div>
      <h3 id="unknown-title" style={{ marginTop: 6 }}>No help article matches this problem yet</h3>
      <p style={{ marginTop: 8, maxWidth: 560 }}>{unknown.message}</p>
      <div className="unknown-metrics">
        <div className="unknown-metric"><div className="tiny">Confidence</div><div className="v">{score(unknown.evidence_score)}</div></div>
        <div className="unknown-metric"><div className="tiny">Closest match</div><div className="v">{score(unknown.top_similarity)}</div></div>
        <div className="unknown-metric"><div className="tiny">Issue type match</div><div className="v">{score(unknown.intent_match)}</div></div>
      </div>
      <p className="small muted" style={{ marginTop: 12 }}>The assistant offers its best general guidance below. If the customer confirms it worked, it goes to the review queue before it can become a help article.</p>
    </section>
  );
}
