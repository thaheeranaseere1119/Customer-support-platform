import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AnalyticsCards } from "../components/AnalyticsCards";
import { HorizontalBars, StackedBarChart } from "../components/Charts";
import { ErrorState } from "../components/ErrorState";
import { Icon } from "../components/Icon";
import { LoadingState } from "../components/LoadingState";
import { useToast } from "../hooks/useToast";
import { api } from "../services/api";
import type { EvaluationRun } from "../types/api";
import { humanize, num, pct, timeAgo } from "../utils/format";
import { STATUS_SERIES } from "./DashboardPage";

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return <div className="metric-tile"><div className="eyebrow">{label}</div><div className="v">{value}</div>{hint && <div className="tiny muted">{hint}</div>}</div>;
}

function EvaluationView({ run }: { run: EvaluationRun }) {
  const m = run.metrics;
  const k = Object.keys(m.retrieval).find((x) => x.startsWith("recall_at_")) ?? "recall_at_10";
  const ndcg = Object.keys(m.retrieval).find((x) => x.startsWith("ndcg_at_")) ?? "ndcg_at_10";
  return (
    <div className="stack">
      <div className="row small muted"><span className="badge badge-brown">{humanize(run.split)}</span><span>{run.sample_size} de-duplicated samples · {Math.round(run.duration_ms)} ms · {timeAgo(run.created_at)}</span>
        <span className={`badge ${m.leakage_check.evaluated_tickets_found_in_index === 0 ? "badge-known" : "badge-unknown"}`}>Index leakage: {m.leakage_check.evaluated_tickets_found_in_index}</span></div>
      <div className="eyebrow">Classification</div>
      <div className="grid grid-5" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
        <Metric label="Accuracy" value={pct(m.classification.accuracy, 1)} /><Metric label="Precision (macro)" value={pct(m.classification.precision_macro, 1)} />
        <Metric label="Recall (macro)" value={pct(m.classification.recall_macro, 1)} /><Metric label="F1 (macro)" value={pct(m.classification.f1_macro, 1)} />
      </div>
      <div className="eyebrow">Retrieval</div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
        <Metric label={humanize(k).replace("At", "@")} value={pct(m.retrieval[k], 1)} hint="hit rate in top K" /><Metric label="MRR" value={(m.retrieval.mrr ?? 0).toFixed(3)} />
        <Metric label={humanize(ndcg).replace("At", "@")} value={(m.retrieval[ndcg] ?? 0).toFixed(3)} />
      </div>
      <div className="eyebrow">Answer quality</div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
        <Metric label="Groundedness" value={pct(m.rag.groundedness, 1)} /><Metric label="Citation correctness" value={pct(m.rag.citation_correctness, 1)} />
        <Metric label="Citation completeness" value={pct(m.rag.citation_completeness, 1)} /><Metric label="Answer relevance" value={m.rag.answer_relevance?.toFixed(3) ?? "—"} hint="cosine(query, answer)" />
      </div>
      <div className="eyebrow">Unknown detection & end-to-end</div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
        <Metric label="Unknown detection" value={pct(m.unknown_detection.detection_rate, 0)} hint={`${m.unknown_detection.flagged_not_known}/${m.unknown_detection.out_of_taxonomy_samples} out-of-taxonomy flagged`} />
        <Metric label="Success rate" value={pct(m.end_to_end.resolution_success_rate)} /><Metric label="Escalation rate" value={pct(m.end_to_end.escalation_rate)} />
        <Metric label="Avg attempts" value={m.end_to_end.average_attempts.toFixed(2)} /><Metric label="Avg response" value={`${Math.round(m.end_to_end.average_response_ms)} ms`} />
      </div>
      {run.notes && <p className="tiny muted">{run.notes}</p>}
    </div>
  );
}

export function AnalyticsPage() {
  const qc = useQueryClient();
  const { notify } = useToast();
  const [split, setSplit] = useState<"held_out_test" | "calibration">("held_out_test");
  const [limit, setLimit] = useState(60);
  const q = useQuery({ queryKey: ["analytics"], queryFn: api.analytics });
  const runs = useQuery({ queryKey: ["evaluations"], queryFn: api.evaluations });
  const logs = useQuery({ queryKey: ["logs"], queryFn: () => api.logs(15) });
  const evaluate = useMutation({ mutationFn: () => api.evaluate({ split, limit }),
    onSuccess: () => { notify("Evaluation complete.", "success"); qc.invalidateQueries({ queryKey: ["evaluations"] }); qc.invalidateQueries({ queryKey: ["analytics"] }); },
    onError: (e: Error) => notify(e.message, "error") });
  const latest = runs.data?.items[0];
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Reports</h1><p>How well customer problems are being solved, plus quality checks on the assistant using test questions it has never seen.</p></div></div>
      {q.isLoading && <LoadingState />}
      {q.error && <ErrorState message={(q.error as Error).message} onRetry={() => q.refetch()} />}
      {q.data && <>
        <AnalyticsCards stats={q.data.stats} />
        <div className="grid grid-2">
          <section className="card"><div className="eyebrow">Last 14 days</div><h2 className="card-title" style={{ marginBottom: 12 }}>Cases by evidence status</h2>
            <StackedBarChart data={q.data.activity} series={STATUS_SERIES} xKey="date" /></section>
          <section className="card"><div className="eyebrow">Live cases</div><h2 className="card-title" style={{ marginBottom: 12 }}>Top intents</h2>
            <HorizontalBars rows={q.data.intent_distribution.map((r) => ({ label: humanize(r.intent), value: r.count }))} /></section>
          <section className="card"><div className="eyebrow">Sample dataset</div><h2 className="card-title" style={{ marginBottom: 12 }}>Tickets by domain category</h2>
            <HorizontalBars rows={q.data.dataset_category_distribution.map((r) => ({ label: r.category, value: r.count }))} format={num} />
            <p className="tiny muted section-gap">Splits: {Object.entries(q.data.dataset_split_counts).map(([s, n]) => `${humanize(s)} ${num(n)}`).join(" · ")}</p></section>
          <section className="card"><div className="eyebrow">Knowledge & index</div><h2 className="card-title" style={{ marginBottom: 12 }}>Knowledge evolution</h2>
            <dl className="kv">
              <dt>Vector index</dt><dd>{q.data.index.documents} documents · v{q.data.index.index_version} · {humanize(q.data.index.vector_backend)}</dd>
              <dt>Articles</dt><dd>{Object.entries(q.data.knowledge_status_counts).map(([k, v]) => `${k} ${v}`).join(" · ")}</dd>
              <dt>Candidates</dt><dd>{Object.entries(q.data.candidate_status_counts).map(([k, v]) => `${humanize(k)} ${v}`).join(" · ") || "—"}</dd>
              <dt>Feedback</dt><dd>{Object.entries(q.data.feedback_counts).map(([k, v]) => `${humanize(k)} ${v}`).join(" · ") || "—"}</dd>
              <dt>Avg evidence</dt><dd>{q.data.stats.average_evidence_score.toFixed(2)}</dd>
            </dl></section>
        </div>
      </>}
      <section className="card">
        <div className="card-header"><div><div className="eyebrow">Offline evaluation</div><h2 className="card-title">Model evaluation</h2></div>
          <div className="row">
            <label className="sr-only" htmlFor="ev-split">Split</label>
            <select id="ev-split" className="select" style={{ width: "auto" }} value={split} onChange={(e) => setSplit(e.target.value as typeof split)}>
              <option value="held_out_test">Held-out test</option><option value="calibration">Calibration</option></select>
            <label className="sr-only" htmlFor="ev-limit">Sample size</label>
            <select id="ev-limit" className="select" style={{ width: "auto" }} value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[20, 60, 120].map((n) => <option key={n} value={n}>{n} samples</option>)}</select>
            <button type="button" className="btn btn-primary" disabled={evaluate.isPending} onClick={() => evaluate.mutate()}>
              <Icon name="chart" size={16} />{evaluate.isPending ? "Evaluating…" : "Run evaluation"}</button>
          </div></div>
        {runs.isLoading && <LoadingState />}
        {latest ? <EvaluationView run={latest} /> : !runs.isLoading && <p className="muted small">No evaluation runs yet. Run one to compute classification, retrieval, RAG and end-to-end metrics.</p>}
        {runs.data && runs.data.items.length > 1 && (
          <div className="table-wrap section-gap"><table className="table"><thead><tr><th>Run</th><th>Split</th><th>Samples</th><th>Accuracy</th><th>MRR</th><th>Groundedness</th><th>When</th></tr></thead>
            <tbody>{runs.data.items.map((r) => <tr key={r.id}><td>#{r.id}</td><td>{humanize(r.split)}</td><td>{r.sample_size}</td><td>{pct(r.metrics.classification.accuracy, 1)}</td>
              <td>{(r.metrics.retrieval.mrr ?? 0).toFixed(3)}</td><td>{pct(r.metrics.rag.groundedness, 1)}</td><td className="tiny muted">{timeAgo(r.created_at)}</td></tr>)}</tbody></table></div>
        )}
      </section>
      <section className="card">
        <div className="card-header"><div><div className="eyebrow">Observability</div><h2 className="card-title">Recent system events</h2></div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => logs.refetch()}><Icon name="refresh" size={14} />Refresh</button></div>
        {logs.error && <ErrorState message={(logs.error as Error).message} />}
        <div className="table-wrap"><table className="table"><thead><tr><th>When</th><th>Event</th><th>Request</th><th>Case</th><th>Details</th></tr></thead>
          <tbody>{logs.data?.items.map((l) => (
            <tr key={l.id}><td className="tiny muted">{timeAgo(l.created_at)}</td><td><span className="badge badge-neutral">{l.event}</span></td><td className="mono">{l.request_id ?? "—"}</td><td className="mono">{l.case_id ?? "—"}</td>
              <td className="tiny">{["intent", "evidence_score", "outcome", "feedback", "total_latency_ms", "llm_latency_ms", "retrieval_latency_ms", "num_sources"].filter((k) => k in l.payload).map((k) => `${k}=${String(l.payload[k])}`).join(" · ")}</td></tr>))}</tbody></table></div>
      </section>
    </div>
  );
}
