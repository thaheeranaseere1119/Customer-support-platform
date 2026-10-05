import type { MemoryState } from "../types/api";
import { humanize } from "../utils/format";

export function MemoryPanel({ memory, summary }: { memory: MemoryState; summary?: string }) {
  const empty = !memory || Object.keys(memory).length === 0;
  return (
    <section className="card memory-panel" aria-labelledby="memory-title">
      <div className="card-header"><div><h3 id="memory-title" className="card-title">What the assistant knows</h3></div></div>
      {empty ? <p className="small muted">Nothing yet. This fills in as the conversation goes on.</p> : (
        <dl>
          <dt>Issue</dt><dd>{memory.issue || "—"}</dd>
          <dt>Intent</dt><dd>{memory.intent_display || humanize(memory.intent) || "—"}</dd>
          <dt>Product</dt><dd>{memory.product || "—"}</dd>
          <dt>Details</dt><dd>{memory.entities?.length ? memory.entities.map((e) => `${humanize(e.type)}: ${e.value}`).join(" · ") : "—"}</dd>
          <dt>Already tried</dt><dd>{memory.troubleshooting?.length ? memory.troubleshooting.join("; ") : "—"}</dd>
          <dt>Context</dt><dd>{memory.customer_context?.length ? memory.customer_context.join(", ") : "—"}</dd>
          <dt>Resolutions</dt><dd>{memory.previous_resolutions?.length
            ? memory.previous_resolutions.map((r) => `${r.case_id} #${r.attempt}: ${r.status}`).join(" · ") : "—"}</dd>
          <dt>Feedback</dt><dd>{memory.feedback?.length ? memory.feedback.map((f) => `#${f.attempt} ${humanize(f.outcome)}`).join(" · ") : "—"}</dd>
        </dl>
      )}
      {summary && (
        <details className="details section-gap">
          <summary>Context the assistant uses</summary>
          <p className="details-body tiny muted" style={{ margin: 0 }}>{summary}</p>
        </details>
      )}
    </section>
  );
}
