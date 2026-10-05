import type { Resolution } from "../types/api";
import { humanize } from "../utils/format";
import { StatusBadge } from "./Badges";
import { Citation, CitedText } from "./Citation";
import { Icon } from "./Icon";

export function ResolutionCard({ resolution, attempt }: { resolution: Resolution; attempt: number }) {
  const removed = resolution.guard_report?.removed_steps?.length ?? 0;
  return (
    <section className={`resolution-card ${resolution.status}`} aria-labelledby="resolution-title">
      <div className="card-header" style={{ marginBottom: 0 }}>
        <div>
          <div className="eyebrow">Attempt {attempt}</div>
          <h3 id="resolution-title" className="card-title">Suggested answer</h3>
        </div>
        <div className="row">
          <StatusBadge status={resolution.status} />
          <span className={`badge ${resolution.is_candidate ? "badge-uncertain" : "badge-known"}`}>{resolution.is_candidate ? "Not yet verified" : "Verified answer"}</span>
        </div>
      </div>
      <p className="resolution-summary"><CitedText text={resolution.summary} /></p>
      <div className="diagnosis"><strong>Diagnosis · </strong><CitedText text={resolution.diagnosis} /></div>

      <ol className="steps">
        {resolution.steps.map((step, i) => (
          <li key={i} className={`step ${step.kind === "information_gathering" ? "info" : ""} ${step.already_attempted ? "tried" : ""}`}>
            <div>
              <span className="step-text">{step.text}</span>{" "}
              {step.citations.map((c) => <Citation key={c} id={c} />)}
              <div className="row" style={{ marginTop: 4 }}>
                {step.kind === "information_gathering" && <span className="badge badge-info">Information to collect</span>}
                {step.already_attempted && <span className="badge badge-neutral"><Icon name="check" size={12} />Customer already tried</span>}
                {step.kind === "resolution" && step.citations.length === 0 && <span className="badge badge-unknown">No source</span>}
              </div>
            </div>
          </li>
        ))}
      </ol>

      {resolution.follow_up_question && (
        <div className="followup-box section-gap"><Icon name="chat" /><div><strong>Ask the customer: </strong>{resolution.follow_up_question}</div></div>
      )}
      {resolution.warnings.length > 0 && (
        <div className="warning-box section-gap" role="note"><Icon name="alert" />
          <ul style={{ margin: 0, paddingLeft: 18 }}>{resolution.warnings.map((w, i) => <li key={i}><CitedText text={w} /></li>)}</ul>
        </div>
      )}
      {resolution.escalation && (
        <div className="escalation-box section-gap" role="alert"><Icon name="shield" size={22} />
          <div><strong>Escalation recommended</strong><br /><CitedText text={resolution.escalation_reason || "Escalate to a human agent."} /></div>
        </div>
      )}
      <div className="row tiny muted section-gap">
{resolution.insufficient_evidence && <span className="badge badge-unknown">No matching help article</span>}
        <details className="details" style={{ flex: 1 }}>
          <summary>How this answer was written</summary>
          <div className="details-body tiny">Written by <b>{humanize(resolution.generator)}</b> using only the sources above. Safety check removed {removed} unsupported step(s).</div>
        </details>
      </div>
    </section>
  );
}
