import type { Candidate } from "../types/api";
import { humanize, num, ORIGIN_LABEL, score, timeAgo } from "../utils/format";

const STATUS = { pending_review: "badge-uncertain", approved: "badge-known", rejected: "badge-unknown" } as const;

export function CandidateTable({ items, onReview }: { items: Candidate[]; onReview: (c: Candidate) => void }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr><th>ID</th><th>Customer problem</th><th>Issue type</th><th>Source</th><th>Confidence</th><th>Reports</th><th>Customer said</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {items.map((c) => (
            <tr key={c.id}>
              <td className="mono">{c.id}<div className="tiny muted">{timeAgo(c.created_at)}</div></td>
              <td style={{ minWidth: 240 }}><span className="clamp-2">{c.complaint}</span></td>
              <td className="small">{c.intent === "unknown" ? <span className="muted">Not set</span> : humanize(c.intent)}</td>
              <td className="small">{ORIGIN_LABEL[c.origin] ?? c.origin}</td>
              <td><b>{score(c.evidence_score)}</b></td>
              <td>{num(c.occurrences)}×</td>
              <td className="small">{humanize(c.customer_feedback)}</td>
              <td><span className={`badge ${STATUS[c.status]}`}>{humanize(c.status)}</span>
                {c.approved_article_id && <div className="tiny mono" style={{ marginTop: 4 }}>→ {c.approved_article_id}</div>}</td>
              <td><button type="button" className="btn btn-ghost btn-sm" onClick={() => onReview(c)}>{c.status === "pending_review" ? "Review" : "View"}</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
