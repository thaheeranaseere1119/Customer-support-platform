import { useState } from "react";
import { Link } from "react-router-dom";
import type { FeedbackResponse, ResolveResponse } from "../types/api";
import { score } from "../utils/format";
import { StatusBadge } from "./Badges";
import { Icon } from "./Icon";

interface Props {
  attempts: ResolveResponse[];
  maxAttempts: number;
  feedback: FeedbackResponse | null;
  busy: boolean;
  onRetry: (additionalInfo?: string) => void;
}

/** Attempt timeline + the outcome of the latest feedback (retry, more info, candidate, escalation). */
export function AdaptiveResolutionCard({ attempts, maxAttempts, feedback, busy, onRetry }: Props) {
  const [info, setInfo] = useState("");
  const current = attempts[attempts.length - 1];
  return (
    <section className="card" aria-labelledby="adaptive-title">
      <div className="card-header">
        <div><h3 id="adaptive-title" className="card-title">Attempt {current?.attempt.attempt_number ?? 0} of {maxAttempts}</h3></div>
        {current && <Link className="btn btn-ghost btn-sm" to={`/admin/cases/${current.case_id}`}>Case {current.case_id} <Icon name="arrow" size={14} /></Link>}
      </div>
      <div className="attempts">
        {Array.from({ length: maxAttempts }, (_, i) => {
          const a = attempts.find((x) => x.attempt.attempt_number === i + 1);
          return (
            <div key={i} className={`attempt-dot ${a && a === current ? "current" : ""} ${a ? "" : "future"}`}>
              Attempt {i + 1}{a ? <> · <StatusBadge status={a.resolution.status} /> {score(a.retrieval.evidence_score)}</> : " · pending"}
            </div>
          );
        })}
      </div>

      {feedback && (
        <div className="section-gap">
          {feedback.next_action === "closed" && (
            <div className="outcome-banner success"><Icon name="check" size={22} /><div><strong>Resolved.</strong><p className="small">{feedback.message}</p></div></div>
          )}
          {feedback.next_action === "candidate_created" && (
            <div className="outcome-banner candidate"><Icon name="sparkle" size={22} /><div className="stack-sm">
              <strong>Sent to the review queue</strong>
              <p className="small">{feedback.message}</p>
              <div className="row"><span className="badge badge-info mono">{feedback.candidate_id}</span>
                <Link to="/admin/candidates" className="btn btn-primary btn-sm">Open review queue <Icon name="arrow" size={14} /></Link></div>
            </div></div>
          )}
          {feedback.next_action === "escalated" && (
            <div className="outcome-banner escalated" role="alert"><Icon name="shield" size={22} /><div><strong>Escalated to an agent</strong><p className="small">{feedback.message}</p></div></div>
          )}
          {feedback.next_action === "retry" && (
            <div className="outcome-banner retry"><Icon name="refresh" size={22} className={busy ? "spin" : undefined} /><div className="stack-sm">
              <strong>Trying again · attempt {feedback.attempt_number + 1}</strong>
              <p className="small">{feedback.message}</p>
              {!busy && <div><button type="button" className="btn btn-primary btn-sm" onClick={() => onRetry()}>Run attempt {feedback.attempt_number + 1}</button></div>}
            </div></div>
          )}
          {feedback.next_action === "provide_more_info" && (
            <div className="outcome-banner retry"><Icon name="info" size={22} /><div className="stack-sm" style={{ flex: 1 }}>
              <strong>Partly solved: add more details</strong>
              <p className="small">{feedback.message}</p>
              <label className="sr-only" htmlFor="more-info">Additional information</label>
              <textarea id="more-info" className="textarea" style={{ minHeight: 80 }} maxLength={1000} value={info}
                placeholder="e.g. The error message says 'No SIM' and it started after a software update" onChange={(e) => setInfo(e.target.value)} />
              <div><button type="button" className="btn btn-primary btn-sm" disabled={busy || info.trim().length < 3}
                onClick={() => onRetry(info.trim())}>Retry with this information</button></div>
            </div></div>
          )}
        </div>
      )}
    </section>
  );
}
