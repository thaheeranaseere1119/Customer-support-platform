import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { CandidateTable } from "../components/CandidateTable";
import { ErrorState } from "../components/ErrorState";
import { Icon } from "../components/Icon";
import { LoadingState } from "../components/LoadingState";
import { Modal } from "../components/Modal";
import { useToast } from "../hooks/useToast";
import { api } from "../services/api";
import type { Candidate } from "../types/api";
import { humanize, LIVE_ORIGINS, num, ORIGIN_LABEL, score } from "../utils/format";

const TABS = [["", "All"], ["pending_review", "Pending review"], ["approved", "Approved"], ["rejected", "Rejected"]] as const;

type Counts = Record<string, number>;
/** The three stages of knowledge evolution; each one is a filter over the same candidate queue. */
const STEPS = [
  { title: "Confirmed by customers", icon: "chat", status: "", origin: "live_feedback",
    hint: "A customer said a suggested fix worked", count: (_c: Counts, o: Counts) => o.live_feedback ?? 0 },
  { title: "Waiting for review", icon: "shield", status: "pending_review", origin: "",
    hint: "Check it, edit it, then approve or reject", count: (c: Counts) => c.pending_review ?? 0 },
  { title: "Published as help articles", icon: "layers", status: "approved", origin: "",
    hint: "Now used by the assistant and the help center", count: (c: Counts) => c.approved ?? 0 },
];

function buildContent(c: Candidate): string {
  const steps = c.proposed_resolution.replace(/\s*\[[^\]]+\]/g, "");
  return `Symptoms: ${c.complaint}\nResolution steps:\n${steps}\nEscalate when: The steps above do not resolve the issue.\nCaution: Human-verified from ${c.id}.`;
}

export function CandidatesPage() {
  const qc = useQueryClient();
  const { notify } = useToast();
  const [tab, setTab] = useState<string>("pending_review");
  const [origin, setOrigin] = useState("");
  const [page, setPage] = useState(1);
  const [active, setActive] = useState<Candidate | null>(null);
  const [form, setForm] = useState({ title: "", content: "", intent: "", notes: "", reviewer: "support-lead" });
  const list = useQuery({ queryKey: ["candidates", tab, origin, page], queryFn: () => api.candidates({ status: tab, origin, page, page_size: 15 }) });
  const intents = useQuery({ queryKey: ["intents"], queryFn: api.intents });
  // Agent fixes are chat replies to one customer: show what is already published for the issue type to avoid duplicates.
  const agentFix = active?.origin === "agent_resolved" && active.status === "pending_review";
  const related = useQuery({ queryKey: ["knowledge", "related", form.intent], enabled: agentFix && !!form.intent,
    queryFn: () => api.knowledge({ status: "ACTIVE", intent: form.intent, page_size: 5 }) });
  const done = () => { setActive(null); qc.invalidateQueries(); };
  const approve = useMutation({
    mutationFn: () => api.approve(active!.id, { reviewer: form.reviewer, notes: form.notes || undefined, title: form.title, content: form.content, intent: form.intent || undefined }),
    onSuccess: (r) => {
      const parts = [r.article ? `Published as ${r.article.article_id}`
        : r.updated_article ? `Added the customer's wording to ${r.updated_article.article_id} (v${r.updated_article.version})` : "Approved",
        r.dataset_record_id ? `added to the dataset as ${r.dataset_record_id}` : ""].filter(Boolean);
      notify(`${parts.join(" and ")}. The assistant can use it now.`, "success"); done();
    },
    onError: (e: Error) => notify(e.message, "error"),
  });
  const reject = useMutation({
    mutationFn: () => api.reject(active!.id, { reviewer: form.reviewer, notes: form.notes || undefined }),
    onSuccess: () => { notify("Rejected. It won't be published.", "info"); done(); },
    onError: (e: Error) => notify(e.message, "error"),
  });
  const openReview = (c: Candidate) => { setActive(c); setForm({ title: c.proposed_title, content: buildContent(c), intent: c.intent === "unknown" ? "" : c.intent, notes: "", reviewer: "support-lead" }); };
  const pending = active?.status === "pending_review";
  const articleCited = active?.sources.find((x) => x.source_type === "knowledge_base")?.source_id;
  const counts = list.data?.counts ?? {};
  const originCounts = list.data?.origin_counts ?? {};
  const activeStep = STEPS.findIndex((st) => st.status === tab && st.origin === origin);
  const emptyMessage = activeStep === 0
    ? "Nothing here yet. When a customer says a suggested fix worked, it will appear here."
    : activeStep === 1 ? "Nothing is waiting for verification." : "Nothing here.";

  return (
    <div className="stack">
      <div className="page-head"><div><h1>Review queue</h1><p>New customer questions that were solved land here: fixes customers confirmed, new questions answered by an existing article, and fixes from agents. Nothing is published or added to the dataset until someone on the team approves it.</p></div></div>
      <div className="grid grid-3" role="group" aria-label="Knowledge evolution workflow steps">
        {STEPS.map((step, i) => {
          const active = activeStep === i;
          const count = step.count(counts, originCounts);
          return (
            <button key={step.title} type="button" className={`stat-card step-card ${active ? "accent" : ""}`} aria-pressed={active}
              onClick={() => { setTab(step.status); setOrigin(step.origin); setPage(1); }}>
              <div className="row" style={{ justifyContent: "space-between", width: "100%" }}>
                <span className="stat-icon"><Icon name={step.icon} /></span>
                <span className="step-count">{num(count)}</span>
              </div>
              <div className="stat-value">{i + 1}</div>
              <div className="stat-label">{step.title}</div>
              <div className="stat-hint">{step.hint}</div>
            </button>
          );
        })}
      </div>
      <section className="card">
        <div className="toolbar">
          <div className="tabs" role="tablist" aria-label="Candidate status">
            {TABS.map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={tab === key} className={`tab ${tab === key ? "active" : ""}`} onClick={() => { setTab(key); setPage(1); }}>{label} ({num(key ? counts[key] ?? 0 : Object.values(counts).reduce((a, b) => a + b, 0))})</button>)}
          </div>
          <label className="sr-only" htmlFor="cand-origin">Origin</label>
          <select id="cand-origin" className="select" value={origin} onChange={(e) => { setOrigin(e.target.value); setPage(1); }}>
            <option value="">All origins</option><option value="live_feedback">Customer confirmed a fix</option><option value="kb_match">New question, answered by an article</option><option value="agent_resolved">Solved by an agent</option><option value="dataset">From past tickets</option><option value="demo_seed">Sample data</option></select>
        </div>
        {list.isLoading && <LoadingState rows={6} />}
        {list.error && <ErrorState message={(list.error as Error).message} onRetry={() => list.refetch()} />}
        {list.data && (list.data.items.length ? <CandidateTable items={list.data.items} onReview={openReview} /> : (
          <div className="empty-state" style={{ padding: 24 }}><p className="muted small">{emptyMessage}</p>
            {activeStep === 0 && <Link to="/admin/support" className="btn btn-primary btn-sm section-gap">Go to Support Resolution</Link>}</div>
        ))}
        {list.data && list.data.total > 15 && (
          <div className="pagination"><button type="button" className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="small">Page {page} of {Math.ceil(list.data.total / 15)}</span>
            <button type="button" className="btn btn-ghost btn-sm" disabled={page * 15 >= list.data.total} onClick={() => setPage(page + 1)}>Next</button></div>
        )}
      </section>

      <Modal open={!!active} onClose={() => setActive(null)} title={pending ? `Review ${active?.id}` : `${active?.id}`} wide
        footer={pending ? <>
          <button type="button" className="btn btn-danger" disabled={reject.isPending || approve.isPending} onClick={() => reject.mutate()}>Reject</button>
          <button type="button" className="btn btn-success" disabled={approve.isPending || reject.isPending || form.title.trim().length < 3 || form.content.trim().length < 10} onClick={() => approve.mutate()}>
            <Icon name="check" size={16} />{approve.isPending ? "Saving…" : active?.origin === "kb_match" ? "Approve and add to article" : "Approve and publish"}</button></> : undefined}>
        {active && <>
          <div className="row"><span className="badge badge-neutral">{ORIGIN_LABEL[active.origin] ?? humanize(active.origin)}</span><span className="badge badge-neutral">Evidence {score(active.evidence_score)}</span>
            <span className="badge badge-neutral">Feedback: {humanize(active.customer_feedback)}</span><span className="badge badge-neutral">Seen {num(active.occurrences)}×</span>
            {active.case_id && <Link className="badge badge-yellow" to={`/admin/cases/${active.case_id}`} onClick={() => setActive(null)}>{active.case_id}</Link>}</div>
          <div className="quote">“{active.complaint}”</div>
          {active.sources.length > 0 && <div className="small">Evidence used: {active.sources.map((s) => s.source_id).join(", ")}</div>}
          {pending && LIVE_ORIGINS.includes(active.origin) && (
            <div className="followup-box small"><div>
              {active.origin === "kb_match"
                ? <>This is a new question that an existing article{articleCited ? ` (${articleCited})` : ""} already answered. Approving adds the
                    customer's wording to that article as a new version, so customers who describe the problem this way find it, and adds the
                    case to the dataset. No duplicate article is created.</>
                : <>Approving publishes a help article and adds this case to the dataset.</>}
              {agentFix && <> These steps are the agent's chat replies to one customer. <strong>Rewrite them as general steps</strong> (remove anything
                specific to this customer, such as a refund already issued) before publishing.</>}
              {agentFix && !!related.data?.items.length && <> Already published for this issue type: {related.data.items.map((k) => `${k.article_id} “${k.title}”`).join(", ")}.
                If that article already covers this fix, reject this one instead of publishing a duplicate.</>}
              {!form.intent && <> <strong>Choose an issue type first</strong>, otherwise it can't be added to the dataset.</>}
            </div></div>
          )}
          {pending ? <>
            <div className="field"><label htmlFor="rv-title">Article title</label><input id="rv-title" className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
            <div className="grid grid-2">
              <div className="field"><label htmlFor="rv-intent">Intent</label><select id="rv-intent" className="select" value={form.intent} onChange={(e) => setForm({ ...form, intent: e.target.value })}>
                <option value="">No issue type</option>{intents.data?.intents.map((i) => <option key={i.name} value={i.name}>{i.display_name}</option>)}</select></div>
              <div className="field"><label htmlFor="rv-reviewer">Reviewer</label><input id="rv-reviewer" className="input" value={form.reviewer} onChange={(e) => setForm({ ...form, reviewer: e.target.value })} /></div>
            </div>
            <div className="field"><label htmlFor="rv-content">Article content (edit before approving)</label>
              <textarea id="rv-content" className="textarea" style={{ minHeight: 200 }} value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} /></div>
            <div className="field"><label htmlFor="rv-notes">Review notes</label><input id="rv-notes" className="input" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
          </> : <>
            <pre className="content-pre">{active.proposed_resolution}</pre>
            <dl className="kv"><dt>Status</dt><dd>{humanize(active.status)}</dd><dt>Reviewer</dt><dd>{active.reviewer ?? "—"}</dd><dt>Notes</dt><dd>{active.review_notes ?? "—"}</dd>
              <dt>Trusted article</dt><dd>{active.approved_article_id ?? "—"}</dd>
              {LIVE_ORIGINS.includes(active.origin) && <><dt>Added to dataset</dt><dd>{active.dataset_record_ids.filter((r) => r.startsWith("TELCO-LIVE-")).join(", ") || "—"}</dd></>}</dl>
          </>}
        </>}
      </Modal>
    </div>
  );
}
