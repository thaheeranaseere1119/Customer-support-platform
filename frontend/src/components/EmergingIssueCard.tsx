import type { EmergingIssue } from "../types/api";
import { num, score, timeAgo } from "../utils/format";
import { Icon } from "./Icon";

const STATUS = { NEW: "badge-unknown", UNDER_REVIEW: "badge-uncertain", APPROVED: "badge-known", REJECTED: "badge-neutral" } as const;

interface Props {
  issue: EmergingIssue;
  compact?: boolean;
  onView?: () => void;
  onReview?: () => void;
  onReject?: () => void;
  onCreateIntent?: () => void;
}

export function EmergingIssueCard({ issue, compact, onView, onReview, onReject, onCreateIntent }: Props) {
  const open = issue.status === "NEW" || issue.status === "UNDER_REVIEW";
  return (
    <article className="issue-card">
      <div className="row"><span className={`badge ${STATUS[issue.status]}`}>{issue.status.replace("_", " ")}</span>
        <span className="tiny muted mono">{issue.id}</span><span className="spacer" /><span className="tiny muted">{timeAgo(issue.updated_at)}</span></div>
      <h3>{issue.pattern_name}</h3>
      <div className="issue-metrics">
        <div><div className="v">{num(issue.occurrences)}</div><div className="tiny muted">Reports</div></div>
        <div><div className="v">{score(issue.avg_evidence_score)}</div><div className="tiny muted">Avg confidence</div></div>
        <div><div className="v" style={{ fontSize: 16, paddingTop: 8 }}>{issue.suggested_category}</div><div className="tiny muted">Suggested category</div></div>
      </div>
      {!compact && (
        <div className="stack-sm">
          <div className="eyebrow">What customers said</div>
          {issue.example_complaints.slice(0, 3).map((ex) => <div key={ex} className="quote">“{ex}”</div>)}
        </div>
      )}
      {issue.created_intent && <div className="small">Issue type created: <b className="mono">{issue.created_intent}</b>{issue.created_article_id && <> · KB <b className="mono">{issue.created_article_id}</b></>}</div>}
      {!compact && (
        <div className="row">
          {onView && <button type="button" className="btn btn-ghost btn-sm" onClick={onView}><Icon name="eye" size={14} />Members</button>}
          {open && onReview && issue.status === "NEW" && <button type="button" className="btn btn-ghost btn-sm" onClick={onReview}>Start review</button>}
          {open && onReject && <button type="button" className="btn btn-danger btn-sm" onClick={onReject}>Reject</button>}
          {open && onCreateIntent && <button type="button" className="btn btn-primary btn-sm" onClick={onCreateIntent}><Icon name="plus" size={14} />Create issue type</button>}
        </div>
      )}
    </article>
  );
}
