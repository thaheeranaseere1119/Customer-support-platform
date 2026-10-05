import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge, IntentBadge, SeverityBadge, SentimentBadge } from "../components/Badges";
import { SourceProvider } from "../components/Citation";
import { ErrorState } from "../components/ErrorState";
import { Icon } from "../components/Icon";
import { LoadingState } from "../components/LoadingState";
import { ResolutionCard } from "../components/ResolutionCard";
import { SourceCard } from "../components/SourceCard";
import { EvidenceScore } from "../components/EvidenceScore";
import { EntityList } from "../components/EntityList";
import { api } from "../services/api";
import type { Attempt } from "../types/api";
import { caseStatusLabel, humanize, score, timeAgo } from "../utils/format";

function CaseList() {
  const [status, setStatus] = useState("");
  const [evidence, setEvidence] = useState("");
  const [offset, setOffset] = useState(0);
  const q = useQuery({ queryKey: ["cases", status, evidence, offset], queryFn: () => api.cases({ status, evidence_status: evidence, limit: 20, offset }) });
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Cases</h1><p>Every customer request, with each attempt the assistant made and how the customer responded.</p></div>
        <Link to="/admin/support" className="btn btn-primary"><Icon name="plus" size={16} />New resolution</Link></div>
      <section className="card">
        <div className="toolbar">
          <label className="sr-only" htmlFor="case-status">Status</label>
          <select id="case-status" className="select" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
            <option value="">All statuses</option>
            {["awaiting_feedback", "resolved", "candidate_submitted", "needs_more_info", "retry_pending", "escalated"].map((s) => <option key={s} value={s}>{caseStatusLabel(s)}</option>)}
          </select>
          <label className="sr-only" htmlFor="case-evidence">Evidence</label>
          <select id="case-evidence" className="select" value={evidence} onChange={(e) => { setEvidence(e.target.value); setOffset(0); }}>
            <option value="">All evidence</option><option value="known">Known</option><option value="uncertain">Uncertain</option><option value="unknown">Unknown</option>
          </select>
        </div>
        {q.isLoading && <LoadingState rows={5} />}
        {q.error && <ErrorState message={(q.error as Error).message} onRetry={() => q.refetch()} />}
        {q.data && (q.data.items.length === 0 ? <p className="muted small">No cases match these filters.</p> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Case</th><th>Complaint</th><th>Intent</th><th>Evidence</th><th>Status</th><th>Attempts</th><th>Created</th></tr></thead>
            <tbody>{q.data.items.map((c) => (
              <tr key={c.case_id}>
                <td className="mono"><Link to={`/admin/cases/${c.case_id}`}><b>{c.case_id}</b></Link></td>
                <td style={{ minWidth: 240 }}><span className="clamp-2">{c.complaint}</span></td>
                <td className="small">{c.intent_display}</td>
                <td><StatusBadge status={c.evidence_status} /> <b className="small">{score(c.evidence_score)}</b></td>
                <td><span className={`badge ${c.status === "escalated" ? "badge-unknown" : c.status === "resolved" ? "badge-known" : "badge-neutral"}`}>{caseStatusLabel(c.status)}</span></td>
                <td>{c.current_attempt}</td><td className="tiny muted">{timeAgo(c.created_at)}</td>
              </tr>))}</tbody>
          </table></div>
        ))}
        {q.data && q.data.total > 20 && (
          <div className="pagination"><button type="button" className="btn btn-ghost btn-sm" disabled={offset === 0} onClick={() => setOffset(offset - 20)}>Previous</button>
            <span className="small">{offset + 1}–{Math.min(offset + 20, q.data.total)} of {q.data.total}</span>
            <button type="button" className="btn btn-ghost btn-sm" disabled={offset + 20 >= q.data.total} onClick={() => setOffset(offset + 20)}>Next</button></div>
        )}
      </section>
    </div>
  );
}

function AttemptView({ attempt }: { attempt: Attempt }) {
  return (
    <SourceProvider sources={attempt.sources} citations={attempt.citations}>
      <div className="grid grid-2">
        <section className="card"><div className="card-header"><div><div className="eyebrow">Attempt {attempt.attempt_number}</div><h3 className="card-title">Evidence</h3></div>
          <span className="tiny muted">{Math.round(attempt.total_latency_ms)} ms</span></div>
          <EvidenceScore evidence={attempt.evidence} />
          {attempt.additional_info && <div className="followup-box section-gap">Additional info: {attempt.additional_info}</div>}
          {attempt.excluded_source_ids.length > 0 && <p className="tiny muted section-gap">Excluded sources: {attempt.excluded_source_ids.join(", ")}</p>}
          <div className="stack-sm section-gap">{attempt.sources.map((s) => <SourceCard key={s.source_id} source={s} cited={attempt.citations.some((c) => c.source_id === s.source_id)} />)}</div>
        </section>
        <ResolutionCard attempt={attempt.attempt_number} resolution={{
          status: attempt.status, is_candidate: attempt.is_candidate, label: attempt.is_candidate ? "CANDIDATE - NOT VERIFIED" : "VERIFIED RESOLUTION",
          summary: attempt.summary, diagnosis: attempt.diagnosis, steps: attempt.steps, warnings: attempt.warnings, escalation: attempt.escalation,
          escalation_reason: attempt.escalation_reason, insufficient_evidence: attempt.insufficient_evidence, follow_up_question: attempt.follow_up_question,
          generator: attempt.generator, guard_report: {},
        }} />
      </div>
    </SourceProvider>
  );
}

function CaseDetail({ caseId }: { caseId: string }) {
  const q = useQuery({ queryKey: ["case", caseId], queryFn: () => api.caseDetail(caseId) });
  const [selected, setSelected] = useState<number | null>(null);
  if (q.isLoading) return <LoadingState label="Loading case…" />;
  if (q.error) return <ErrorState message={(q.error as Error).message} onRetry={() => q.refetch()} />;
  const c = q.data!;
  const attempt = c.attempts.find((a) => a.attempt_number === selected) ?? c.attempts[c.attempts.length - 1];
  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="page-head"><div><Link to="/admin/cases" className="small">← All cases</Link><h1 style={{ marginTop: 8 }}>{c.case_id}</h1>
        <p>{c.complaint}</p></div>
        <div className="row"><StatusBadge status={c.evidence_status} /><span className={`badge ${c.status === "escalated" ? "badge-unknown" : "badge-brown"}`}>{caseStatusLabel(c.status)}</span></div></div>
      <div className="grid grid-3">
        <section className="card"><div className="eyebrow">Analysis</div>
          <div className="row section-gap"><IntentBadge intent={c.analysis.intent} display={c.analysis.intent_display} /><SeverityBadge severity={c.analysis.severity} /><SentimentBadge sentiment={c.analysis.sentiment} /></div>
          <dl className="kv section-gap"><dt>Category</dt><dd>{c.category}</dd><dt>Product</dt><dd>{humanize(c.product)}</dd><dt>Input</dt><dd>{humanize(c.input_mode)}{c.guided_category ? ` · ${c.guided_category}` : ""}</dd>
            <dt>Memory used</dt><dd>{c.used_memory ? "Yes" : "No"}</dd><dt>Request</dt><dd className="mono">{c.request_id}</dd></dl>
          <div className="section-gap"><EntityList entities={c.analysis.entities} memory={c.analysis.memory_entities} /></div>
        </section>
        <section className="card"><div className="eyebrow">Attempts ({c.attempts.length} / {c.max_attempts})</div>
          <div className="stack-sm section-gap">{c.attempts.map((a) => (
            <button key={a.id} type="button" className={`source-card ${attempt?.id === a.id ? "cited" : ""}`} onClick={() => setSelected(a.attempt_number)}>
              <div className="source-head"><b>Attempt {a.attempt_number}</b><StatusBadge status={a.status} /><span className="spacer" /><b>{score(a.evidence_score)}</b></div>
              <div className="tiny muted clamp-2">{a.summary}</div></button>))}</div>
        </section>
        <section className="card"><div className="eyebrow">Feedback & knowledge</div>
          <div className="stack-sm section-gap">
            {c.feedback.length === 0 && <p className="small muted">No feedback recorded yet.</p>}
            {c.feedback.map((f) => <div key={f.id} className="row small"><span className="badge badge-neutral">#{f.attempt_number}</span><b>{humanize(f.outcome)}</b>{f.comment && <span className="muted">“{f.comment}”</span>}</div>)}
            {c.candidates.map((cd) => <div key={cd.id} className="row small"><Icon name="sparkle" size={14} /><span className="mono">{cd.id}</span><span className="badge badge-info">{humanize(cd.status)}</span>
              {cd.approved_article_id && <Link to="/admin/knowledge" className="mono">→ {cd.approved_article_id}</Link>}</div>)}
            {c.escalation_reason && <div className="escalation-box"><Icon name="shield" /><span>{c.escalation_reason}</span></div>}
          </div>
        </section>
      </div>
      {attempt && <AttemptView attempt={attempt} />}
    </div>
  );
}

export function CasesPage() {
  const { caseId } = useParams();
  return caseId ? <CaseDetail caseId={caseId} /> : <CaseList />;
}
