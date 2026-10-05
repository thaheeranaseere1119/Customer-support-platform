import { useState } from "react";
import type { FeedbackOutcome } from "../types/api";
import { Icon } from "./Icon";

export function FeedbackCard({ busy, onFeedback }: { busy: boolean; onFeedback: (o: FeedbackOutcome, comment?: string) => void }) {
  const [comment, setComment] = useState("");
  return (
    <section className="feedback-card" aria-labelledby="feedback-title">
      <div className="eyebrow">Customer feedback</div>
      <h3 id="feedback-title">Did this solve the problem?</h3>
      <label className="sr-only" htmlFor="feedback-comment">Optional comment</label>
      <input id="feedback-comment" className="input" style={{ marginTop: 12, background: "rgba(255,255,255,.7)" }} maxLength={1000}
        placeholder="Optional comment from the customer…" value={comment} onChange={(e) => setComment(e.target.value)} />
      <div className="feedback-buttons">
        <button type="button" className="btn btn-success" disabled={busy} onClick={() => onFeedback("solved", comment)}><Icon name="thumbUp" size={16} />Yes, solved</button>
        <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => onFeedback("partially_solved", comment)}><Icon name="half" size={16} />Partly</button>
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => onFeedback("not_solved", comment)}><Icon name="thumbDown" size={16} />No, still not solved</button>
      </div>
    </section>
  );
}
