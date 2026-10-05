import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useToast } from "../hooks/useToast";
import { api } from "../services/api";
import type { FeedbackOutcome } from "../types/api";
import { score } from "../utils/format";
import { StatusBadge } from "./Badges";
import { Citation, CitedText, SourceProvider } from "./Citation";
import { Icon } from "./Icon";

/**
 * The full grounded resolution for one assistant turn in the conversation: cited steps
 * (clickable KB / ticket citations), warnings, escalation, and, for the latest attempt,
 * the feedback question that drives the adaptive workflow.
 */
export function AssistantResolution({ caseId, attempt, sessionId, audience = "admin", interactive = true }:
  { caseId: string; attempt: number; sessionId: string; audience?: "admin" | "customer"; interactive?: boolean }) {
  // `audience` controls wording and which details are shown; `interactive` only controls the
  // feedback buttons. Customers never see internal scores, regardless of interactivity.
  const customer = audience === "customer";
  const qc = useQueryClient();
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const [moreInfo, setMoreInfo] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["case", caseId], queryFn: () => api.caseDetail(caseId) });
  const data = q.data;
  const a = data?.attempts.find((x) => x.attempt_number === attempt);
  if (q.isLoading) return <div className="tiny muted">Loading resolution…</div>;
  if (!data || !a) return null;

  const isCurrent = data.current_attempt === attempt;
  const awaiting = isCurrent && data.status === "awaiting_feedback" && interactive;
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["conversation", sessionId] });
    qc.invalidateQueries({ queryKey: ["case", caseId] });
    qc.invalidateQueries({ queryKey: ["analytics"] });
  };
  const retry = async (info?: string) => {
    await api.retryStream({ case_id: caseId, additional_info: info || null }, () => undefined);
    setMoreInfo(null);
  };
  const feedback = async (outcome: FeedbackOutcome) => {
    setBusy(true);
    try {
      const res = await api.feedback({ case_id: caseId, outcome, attempt_number: attempt });
      // Customers see the outcome in the chat itself; admins also get a status toast.
      const tell = (text: string, kind: "info" | "success" | "error") => { if (!customer) notify(text, kind); };
      if (res.next_action === "retry") {
        tell("Not solved. Trying again with alternative evidence…", "info");
        await retry();
      } else if (res.next_action === "provide_more_info") {
        setMoreInfo("");
        tell("Partially solved. Add more details, then retry.", "info");
      } else if (res.next_action === "candidate_created") {
        tell("Saved as candidate knowledge, pending human verification.", "success");
      } else if (res.next_action === "escalated") {
        tell("Maximum attempts reached. Escalated to a human agent.", "error");
      } else {
        tell("Marked as solved.", "success");
      }
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy(false);
      refresh();
    }
  };
  const submitInfo = async () => {
    if (!moreInfo || moreInfo.trim().length < 3) return;
    setBusy(true);
    try {
      await retry(moreInfo.trim());
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy(false);
      refresh();
    }
  };

  const resolutionSteps = a.steps;

  if (customer) {
    // Plain wording written for customers; agent-only steps ("" ) are left out.
    const customerSteps = resolutionSteps
      .map((st) => ({ ...st, text: st.customer_text ?? st.text }))
      .filter((st) => st.text.trim().length > 0);
    // Customer view: plain steps, sources as links to help articles, no internal IDs or scores.
    const kbSources = a.citations.filter((c) => c.source_type === "knowledge_base");
    const caseCount = a.citations.filter((c) => c.source_type !== "knowledge_base").length;
    const gathering = resolutionSteps.every((st) => st.kind === "information_gathering");
    // For new or partly matched questions, also point to the closest help articles.
    const cited = new Set(a.citations.map((c) => c.source_id));
    const related = a.status === "known" ? [] : a.sources
      .filter((s) => s.source_type === "knowledge_base" && !s.extra?.general && !cited.has(s.source_id))
      // Only articles with a real signal (shared keywords plus meaning), strongest first.
      .filter((s) => s.keyword_score + s.semantic_score >= 0.45)
      .sort((x, y) => (y.keyword_score + y.semantic_score) - (x.keyword_score + x.semantic_score))
      .filter((s, i, all) => all.findIndex((x) => x.source_id === s.source_id) === i)
      .slice(0, 3);
    return (
      <div className="cr" aria-label="Suggested solution">
        <ol className={`cr-steps ${gathering ? "checklist" : ""}`}>
          {customerSteps.map((step, i) => (
            <li key={i} className={step.already_attempted ? "tried" : ""}>
              {step.text}{step.already_attempted && <em> (you've already tried this)</em>}
            </li>))}
        </ol>
        {(kbSources.length > 0 || caseCount > 0) && (
          <p className="cr-sources">Based on{" "}
            {kbSources.map((c, i) => (
              <span key={c.source_id}>{i > 0 && ", "}<Link to={`/help/article/${c.source_id}`}>{c.title.replace(/^KB-\d+:\s*/, "")}</Link></span>))}
            {caseCount > 0 && <>{kbSources.length > 0 ? " and " : ""}{caseCount} similar solved case{caseCount > 1 ? "s" : ""}</>}
          </p>
        )}
        {related.length > 0 && (
          <div className="cr-related">
            <span>You might also find these helpful:</span>
            <ul>{related.map((s) => <li key={s.source_id}><Link to={`/help/article/${s.source_id}`}>{s.title.replace(/^KB-\d+:\s*/, "")}</Link></li>)}</ul>
          </div>
        )}
        {a.is_candidate && !gathering && <p className="cr-hint">Let me know how these go. It helps us make our answers even better.</p>}
        {awaiting && moreInfo === null && (
          <div className="cr-feedback">
            <span>Did this solve it?</span>
            <div>
              <button type="button" disabled={busy} onClick={() => feedback("solved")}>Yes, all sorted</button>
              <button type="button" disabled={busy} onClick={() => feedback("partially_solved")}>Partly</button>
              <button type="button" disabled={busy} onClick={() => feedback("not_solved")}>I still need help</button>
            </div>
          </div>
        )}
        {isCurrent && moreInfo !== null && (
          <div className="cr-feedback">
            <label htmlFor={`info-${caseId}`}>What else have you noticed?</label>
            <textarea id={`info-${caseId}`} className="s-input" rows={3} maxLength={1000} value={moreInfo}
              onChange={(e) => setMoreInfo(e.target.value)} placeholder="e.g. It happens only on 4G; Wi-Fi works fine" />
            <div><button type="button" disabled={busy || moreInfo.trim().length < 3} onClick={submitInfo}>Send and try again</button></div>
          </div>
        )}
        {isCurrent && (data.status === "candidate_submitted" || data.status === "resolved") && <p className="cr-done">Great, glad that's sorted.</p>}
        {isCurrent && data.status === "escalated" && <p className="cr-done">We've passed this to our support team. Someone will reply here.</p>}
      </div>
    );
  }

  return (
    <SourceProvider sources={a.sources} citations={a.citations}>
      <div className="chat-resolution" aria-label={`Resolution for ${caseId} attempt ${attempt}`}>
        <div className="row">
          <StatusBadge status={a.status} />
          <span className={`badge ${a.is_candidate ? "badge-uncertain" : "badge-known"}`}>
            {a.is_candidate ? "CANDIDATE - NOT VERIFIED" : "VERIFIED RESOLUTION"}</span>
          <span className="tiny muted">Evidence {score(a.evidence_score)} · attempt {attempt}/{data.max_attempts}</span>
        </div>
        <ol className="steps" style={{ marginTop: 10 }}>
          {resolutionSteps.map((step, i) => (
            <li key={i} className={`step ${step.kind === "information_gathering" ? "info" : ""} ${step.already_attempted ? "tried" : ""}`}>
              <div>
                <span className="step-text">{step.text}</span>{" "}
                {step.citations.map((c) => <Citation key={c} id={c} />)}
                {step.already_attempted && <div className="tiny muted">Customer already tried this</div>}
                {step.kind === "information_gathering" && <div className="tiny muted">Information to collect (not a fix)</div>}
              </div>
            </li>
          ))}
        </ol>
        {a.citations.length > 0 && (
          <div className="tiny muted" style={{ marginTop: 8 }}>
            Sources: {a.citations.map((c) => <Citation key={c.source_id} id={c.source_id} />)}
          </div>
        )}
        {a.warnings.length > 0 && (
          <div className="warning-box" style={{ marginTop: 10 }}><Icon name="alert" size={16} />
            <ul style={{ margin: 0, paddingLeft: 16 }}>{a.warnings.map((w, i) => <li key={i}><CitedText text={w} /></li>)}</ul></div>
        )}
        {a.escalation && a.escalation_reason && (
          <div className="escalation-box" style={{ marginTop: 10 }}><Icon name="shield" size={16} /><span><CitedText text={a.escalation_reason} /></span></div>
        )}

        {awaiting && moreInfo === null && (
          <div className="chat-feedback">
            <strong>Did this solve the problem?</strong>
            <div className="row" style={{ marginTop: 8 }}>
              <button type="button" className="btn btn-success btn-sm" disabled={busy} onClick={() => feedback("solved")}><Icon name="thumbUp" size={14} />Yes, solved</button>
              <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => feedback("partially_solved")}><Icon name="half" size={14} />Partly</button>
              <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => feedback("not_solved")}><Icon name="thumbDown" size={14} />No, not solved</button>
              {busy && <Icon name="refresh" className="spin" size={16} />}
            </div>
          </div>
        )}
        {isCurrent && moreInfo !== null && (
          <div className="chat-feedback">
            <label htmlFor={`info-${caseId}`}><strong>What else did the customer notice?</strong></label>
            <textarea id={`info-${caseId}`} className="textarea" style={{ minHeight: 70, marginTop: 8 }} maxLength={1000}
              value={moreInfo} onChange={(e) => setMoreInfo(e.target.value)} placeholder="e.g. It only fails on 4G, Wi-Fi works" />
            <button type="button" className="btn btn-primary btn-sm" style={{ marginTop: 8 }} disabled={busy || moreInfo.trim().length < 3}
              onClick={submitInfo}>Retry with this information</button>
          </div>
        )}
        {isCurrent && data.status === "candidate_submitted" && (
          <div className="tiny" style={{ marginTop: 8 }}>Saved as candidate knowledge · <Link to="/admin/candidates">review it</Link></div>
        )}
        {isCurrent && data.status === "escalated" && <div className="escalation-box" style={{ marginTop: 8 }}><Icon name="shield" size={16} />
          {data.escalation_reason}</div>}
        {isCurrent && data.status === "resolved" && <div className="tiny" style={{ marginTop: 8, color: "var(--status-known)" }}>✓ Resolved</div>}
      </div>
    </SourceProvider>
  );
}
