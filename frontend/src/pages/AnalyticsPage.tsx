import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AnalyticsCards } from "../components/AnalyticsCards";
import { HorizontalBars, StackedBarChart } from "../components/Charts";
import { ErrorState } from "../components/ErrorState";
import { Icon } from "../components/Icon";
import { LoadingState } from "../components/LoadingState";
import { useToast } from "../hooks/useToast";
import { api } from "../services/api";
import type { EvaluationRun, RealisticEvaluation, ScoreConfidence } from "../types/api";
import { humanize, num, pct, timeAgo } from "../utils/format";
import { STATUS_SERIES } from "./DashboardPage";

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return <div className="metric-tile"><div className="eyebrow">{label}</div><div className="v">{value}</div>{hint && <div className="tiny muted">{hint}</div>}</div>;
}

/** 95% lower bound for `successes` out of `total` (Wilson score), used when an older run has no stored bound. */
function wilsonLower(successes: number, total: number): number | null {
  if (total <= 0) return null;
  const z = 1.96, p = successes / total;
  const centre = p + (z * z) / (2 * total);
  const margin = z * Math.sqrt((p * (1 - p)) / total + (z * z) / (4 * total * total));
  return Math.max(0, (centre - margin) / (1 + (z * z) / total));
}

/**
 * Every rate is headlined by its 95% lower bound ("the true rate is probably at least ..."), so scores compare
 * fairly and a perfect result on a limited sample is never presented as certain: 8/8 correct reads "≥ 68%".
 * The hint gives the counts and, when it is not perfect, the measured rate.
 */
export function Score({ label, value, ci, hint, decimals = false, noun = "correct" }: {
  label: string; value: number | null | undefined; ci?: ScoreConfidence; hint?: string; decimals?: boolean; noun?: string;
}) {
  if (value === null || value === undefined) return <Metric label={label} value="—" hint={hint} />;
  const fmt = (x: number) => (decimals ? x.toFixed(2) : pct(x, x >= 0.995 ? 0 : 1));
  const counts = ci?.total ? `${ci.successes}/${ci.total} ${noun}` : "";
  if (ci?.lower_95 !== null && ci?.lower_95 !== undefined) {
    const measured = value >= 0.995 ? "" : `measured ${fmt(value)}`;
    return <Metric label={label} value={`≥ ${decimals ? ci.lower_95.toFixed(2) : pct(ci.lower_95, 0)}`}
      hint={[counts, measured, "95% lower bound", hint].filter(Boolean).join(" · ")} />;
  }
  return <Metric label={label} value={value >= 0.995 ? "—" : fmt(value)}
    hint={[counts, value >= 0.995 ? "perfect on this sample, too few results to bound" : "", hint].filter(Boolean).join(" · ") || undefined} />;
}

/** Bound for an older run that stored only the rate: assume it was measured on `n` items. */
const estimated = (value: number | null | undefined, n: number): ScoreConfidence | undefined =>
  value === null || value === undefined || n <= 0 ? undefined
    : { successes: Math.round(value * n), total: n, lower_95: wilsonLower(Math.round(value * n), n) };

/** Hand-labelled, customer-style questions: the most realistic measure of answer quality. */
function RealisticView({ r }: { r: RealisticEvaluation }) {
  const [showAll, setShowAll] = useState(false);
  const failures = showAll ? r.failures : r.failures.slice(0, 5);
  const c = (key: string, value: number) => r.confidence?.[key] ?? estimated(value, r.questions);
  return (
    <section className="stack" aria-labelledby="realistic-title">
      <div>
        <div id="realistic-title" className="eyebrow">Realistic customer questions ({r.questions}, labelled by hand)</div>
        <p className="tiny muted" style={{ margin: "4px 0 0" }}>Questions worded the way customers write, across every issue type. These scores are the closest to what customers experience.</p>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        <Score label="Issue type correct" value={r.intent_accuracy} ci={c("intent_accuracy", r.intent_accuracy)} />
        <Score label="Correct article used" value={r.correct_article_first} ci={c("correct_article_first", r.correct_article_first)} hint="answer written from a right article" />
        <Score label="Correct article in top 3" value={r.correct_article_in_top3} ci={c("correct_article_in_top3", r.correct_article_in_top3)} />
        <Score label="Clean customer wording" value={r.clean_customer_wording} ci={c("clean_customer_wording", r.clean_customer_wording)} noun="clean" hint="no jargon, fragments or past-tense notes" />
        <Score label="Answered with steps" value={r.answered_with_steps} ci={c("answered_with_steps", r.answered_with_steps)} noun="answered" />
      </div>
      {r.failures.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <caption className="sr-only">Questions the assistant got wrong</caption>
            <thead><tr><th>Question</th><th>Expected</th><th>Got</th><th>Answered from</th><th>Wording</th></tr></thead>
            <tbody>
              {failures.map((f) => (
                <tr key={f.complaint}>
                  <td>{f.complaint}</td>
                  <td className="small">{humanize(f.expected_intent)}<div className="tiny muted">{f.expected_articles.join(", ")}</div></td>
                  <td className={`small ${f.got_intent === f.expected_intent ? "" : "text-danger"}`}>{humanize(f.got_intent)}</td>
                  <td className={`small ${f.answered_from && f.expected_articles.includes(f.answered_from) ? "" : "text-danger"}`}>{f.answered_from ?? "No steps"}</td>
                  <td className="small">{f.wording_issues.length ? f.wording_issues.join(", ") : "OK"}</td>
                </tr>))}
            </tbody>
          </table>
          {r.failures.length > 5 && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show fewer" : `Show all ${r.failures.length} misses`}</button>)}
        </div>
      )}
    </section>
  );
}

function EvaluationView({ run }: { run: EvaluationRun }) {
  const m = run.metrics;
  const k = Object.keys(m.retrieval).find((x) => x.startsWith("recall_at_")) ?? "recall_at_10";
  const ndcg = Object.keys(m.retrieval).find((x) => x.startsWith("ndcg_at_")) ?? "ndcg_at_10";
  const n = m.sample?.tested ?? run.sample_size;
  const ci = (key: string, value: number | null | undefined) => m.confidence?.[key] ?? estimated(value, n);
  const templateAnswers = m.generator ? m.generator === "template" : (m.warnings ?? []).some((w) => w.startsWith("Demo mode"));
  const sampleText = m.sample
    ? `${m.sample.unique_complaints} unique complaints × ${m.sample.wordings} wordings = ${m.sample.tested} tested`
    : `${run.sample_size} de-duplicated samples`;
  return (
    <div className="stack">
      <div className="row small muted"><span className="badge badge-brown">{humanize(run.split)}</span><span>{sampleText} · {Math.round(run.duration_ms)} ms · {timeAgo(run.created_at)}</span>
        <span className={`badge ${m.leakage_check.evaluated_tickets_found_in_index === 0 ? "badge-known" : "badge-unknown"}`}>Index leakage: {m.leakage_check.evaluated_tickets_found_in_index}</span></div>
      {m.realistic && <RealisticView r={m.realistic} />}
      <div className="eyebrow" style={{ marginTop: 8 }}>Synthetic {humanize(run.split).toLowerCase()} split (templated tickets)</div>
      {(m.warnings ?? []).map((w) => <div key={w} className="eval-warning" role="note"><Icon name="alert" size={16} /><span>{w}</span></div>)}
      {m.by_wording && (<>
        <div className="eyebrow">Accuracy by wording</div>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}>
          {Object.entries(m.by_wording).map(([wording, w]) => (
            <Score key={wording} label={humanize(wording)} value={w.accuracy}
              ci={{ successes: w.correct, total: w.total, lower_95: w.lower_95 }} />))}
        </div>
      </>)}
      <div className="eyebrow">Classification</div>
      <div className="grid grid-5" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
        <Score label="Accuracy" value={m.classification.accuracy} ci={ci("accuracy", m.classification.accuracy)} />
        <Score label="Precision (macro)" value={m.classification.precision_macro} ci={ci("precision_macro", m.classification.precision_macro)} hint="wrong guesses avoided" />
        <Score label="Recall (macro)" value={m.classification.recall_macro} ci={ci("recall_macro", m.classification.recall_macro)} />
        <Score label="F1 (macro)" value={m.classification.f1_macro} ci={ci("f1_macro", m.classification.f1_macro)} />
      </div>
      <div className="eyebrow">Retrieval</div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
        <Score label={humanize(k).replace("At", "@")} value={m.retrieval[k]} ci={ci(k, m.retrieval[k])} noun="found" hint="right issue type in top K" />
        <Score label="MRR" value={m.retrieval.mrr} ci={ci("mrr", m.retrieval.mrr)} decimals noun="ranked first" />
        <Score label={humanize(ndcg).replace("At", "@")} value={m.retrieval[ndcg]} ci={ci(ndcg, m.retrieval[ndcg])} decimals noun="perfect order" />
      </div>
      <div className="eyebrow">Answer quality</div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
        {templateAnswers
          ? <Metric label="Groundedness" value="Not measured" hint="demo mode copies steps from sources; measured with the LLM on" />
          : <Score label="Groundedness" value={m.rag.groundedness} ci={ci("groundedness", m.rag.groundedness)} noun="steps supported" />}
        <Score label="Citation correctness" value={m.rag.citation_correctness} ci={ci("citation_correctness", m.rag.citation_correctness)} noun="citations on topic" />
        <Metric label="Citation completeness" value="Enforced" hint="the safety check removes any step without a source" />
        <Metric label="Answer relevance" value={m.rag.answer_relevance?.toFixed(3) ?? "—"} hint="cosine(query, answer); scale depends on the embedding model" />
      </div>
      <div className="eyebrow">Unknown detection & end-to-end</div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
        <Score label="Unknown detection" value={m.unknown_detection.detection_rate}
          ci={m.confidence?.unknown_detection ?? estimated(m.unknown_detection.detection_rate, m.unknown_detection.out_of_taxonomy_samples)} noun="out-of-taxonomy flagged" />
        <Metric label="Success rate" value={pct(m.end_to_end.resolution_success_rate)} hint="customers who said it was solved" />
        <Metric label="Escalation rate" value={pct(m.end_to_end.escalation_rate)} />
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
