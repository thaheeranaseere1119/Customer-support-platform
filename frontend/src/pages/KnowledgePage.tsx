import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorState } from "../components/ErrorState";
import { Icon } from "../components/Icon";
import { KnowledgeTable } from "../components/KnowledgeTable";
import { LoadingState } from "../components/LoadingState";
import { Modal } from "../components/Modal";
import { useToast } from "../hooks/useToast";
import { api } from "../services/api";
import type { KnowledgeArticle } from "../types/api";
import { humanize, timeAgo } from "../utils/format";

interface Draft { title: string; content: string; category: string; intent: string; product: string; status: "ACTIVE" | "DRAFT" }
const TEMPLATE = "Symptoms: \nResolution steps:\n1. \n2. \nEscalate when: \nCaution: ";

function ArticleForm({ value, onChange, categories, intents }:
  { value: Draft; onChange: (d: Draft) => void; categories: string[]; intents: { name: string; display_name: string }[] }) {
  const set = (k: keyof Draft) => (e: { target: { value: string } }) => onChange({ ...value, [k]: e.target.value });
  return (
    <>
      <div className="field"><label htmlFor="kb-title">Title</label><input id="kb-title" className="input" value={value.title} onChange={set("title")} /></div>
      <div className="grid grid-2">
        <div className="field"><label htmlFor="kb-cat">Category</label><select id="kb-cat" className="select" value={value.category} onChange={set("category")}>
          <option value="">Select…</option>{categories.map((c) => <option key={c}>{c}</option>)}</select></div>
        <div className="field"><label htmlFor="kb-intent">Intent</label><select id="kb-intent" className="select" value={value.intent} onChange={set("intent")}>
          <option value="">Select…</option>{intents.map((i) => <option key={i.name} value={i.name}>{i.display_name}</option>)}</select></div>
        <div className="field"><label htmlFor="kb-product">Product</label><input id="kb-product" className="input" value={value.product} onChange={set("product")} /></div>
        <div className="field"><label htmlFor="kb-status">Status</label><select id="kb-status" className="select" value={value.status} onChange={set("status")}>
          <option value="DRAFT">DRAFT (not retrievable)</option><option value="ACTIVE">ACTIVE (indexed for retrieval)</option></select></div>
      </div>
      <div className="field"><label htmlFor="kb-content">Content</label><textarea id="kb-content" className="textarea" style={{ minHeight: 220 }} value={value.content} onChange={set("content")} />
        <span className="field-hint">Use “Resolution steps” with numbered lines so steps can be cited individually.</span></div>
    </>
  );
}

export function KnowledgePage() {
  const qc = useQueryClient();
  const { notify } = useToast();
  const [filters, setFilters] = useState({ status: "", category: "", q: "", page: 1 });
  const [params, setParams] = useSearchParams();
  // ?article=KB-031 (from the top-bar search) opens that article directly.
  const openId = params.get("article");
  const setOpenId = (id: string | null) => setParams(id ? { article: id } : {}, { replace: true });
  const [editing, setEditing] = useState<Draft | null>(null);
  const [creating, setCreating] = useState<Draft | null>(null);
  const list = useQuery({ queryKey: ["knowledge", filters], queryFn: () => api.knowledge({ ...filters, page_size: 15 }) });
  const intents = useQuery({ queryKey: ["intents"], queryFn: api.intents });
  const detail = useQuery({ queryKey: ["knowledge-detail", openId], queryFn: () => api.knowledgeDetail(openId!), enabled: !!openId });
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["knowledge"] }); qc.invalidateQueries({ queryKey: ["knowledge-detail"] }); qc.invalidateQueries({ queryKey: ["analytics"] }); };

  const create = useMutation({ mutationFn: (d: Draft) => api.createKnowledge(d), onSuccess: (a) => { notify(`${a.article_id} created (${a.status}).`, "success"); setCreating(null); invalidate(); }, onError: (e: Error) => notify(e.message, "error") });
  const update = useMutation({ mutationFn: (d: Draft) => api.updateKnowledge(openId!, { ...d, change_note: "edited in Knowledge Base" }),
    onSuccess: (a) => { notify(`${a.article_id} saved as version ${a.version}; previous version archived.`, "success"); setEditing(null); invalidate(); }, onError: (e: Error) => notify(e.message, "error") });
  const review = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "reject" }) => (action === "approve" ? api.approve(id, { reviewer: "support-lead" }) : api.reject(id, { reviewer: "support-lead" })),
    onSuccess: (r) => { notify(r.status === "approved" ? `${r.item_id} approved and indexed (index v${r.index_version}).` : `${r.item_id} rejected and archived.`, "success"); invalidate(); },
    onError: (e: Error) => notify(e.message, "error"),
  });

  const categories = intents.data?.categories.map((c) => c.name) ?? [];
  const intentOptions = intents.data?.intents ?? [];
  const valid = (d: Draft | null) => !!d && d.title.trim().length >= 3 && d.content.trim().length >= 10 && !!d.category && !!d.intent;
  const a = detail.data;
  const setFilter = (k: string) => (e: { target: { value: string } }) => setFilters({ ...filters, [k]: e.target.value, page: 1 });

  return (
    <div className="stack">
      <div className="page-head"><div><h1>Help articles</h1><p>Articles used by the assistant and shown on the customer help center. Only published articles are used; every edit is saved as a new version.</p></div>
        <button type="button" className="btn btn-primary" onClick={() => setCreating({ title: "", content: TEMPLATE, category: "", intent: "", product: "", status: "DRAFT" })}><Icon name="plus" size={16} />New article</button></div>
      <section className="card">
        <div className="toolbar">
          <label className="sr-only" htmlFor="kb-search">Search</label>
          <input id="kb-search" className="input" placeholder="Search title, content or ID…" value={filters.q} onChange={setFilter("q")} />
          <label className="sr-only" htmlFor="kb-filter-status">Status</label>
          <select id="kb-filter-status" className="select" value={filters.status} onChange={setFilter("status")}>
            <option value="">All statuses</option><option>ACTIVE</option><option>DRAFT</option><option>ARCHIVED</option></select>
          <label className="sr-only" htmlFor="kb-filter-cat">Category</label>
          <select id="kb-filter-cat" className="select" value={filters.category} onChange={setFilter("category")}>
            <option value="">All categories</option>{categories.map((c) => <option key={c}>{c}</option>)}</select>
        </div>
        {list.isLoading && <LoadingState rows={6} />}
        {list.error && <ErrorState message={(list.error as Error).message} onRetry={() => list.refetch()} />}
        {list.data && (list.data.items.length ? <KnowledgeTable items={list.data.items} onOpen={(x: KnowledgeArticle) => setOpenId(x.article_id)} /> : <p className="muted small">No articles match.</p>)}
        {list.data && (
          <div className="pagination">
            <button type="button" className="btn btn-ghost btn-sm" disabled={filters.page <= 1} onClick={() => setFilters({ ...filters, page: filters.page - 1 })}>Previous</button>
            <span className="small">Page {filters.page} of {Math.max(1, Math.ceil(list.data.total / 15))} · {list.data.total} articles</span>
            <button type="button" className="btn btn-ghost btn-sm" disabled={filters.page * 15 >= list.data.total} onClick={() => setFilters({ ...filters, page: filters.page + 1 })}>Next</button>
          </div>
        )}
      </section>

      <Modal open={!!openId && !editing} onClose={() => setOpenId(null)} title={a ? `${a.article_id} · v${a.version}` : "Article"} wide
        footer={a && <>
          {a.status === "DRAFT" && <>
            <button type="button" className="btn btn-danger" disabled={review.isPending} onClick={() => review.mutate({ id: a.article_id, action: "reject" })}>Reject draft</button>
            <button type="button" className="btn btn-success" disabled={review.isPending} onClick={() => review.mutate({ id: a.article_id, action: "approve" })}><Icon name="check" size={16} />Approve & index</button></>}
          <button type="button" className="btn btn-primary" onClick={() => setEditing({ title: a.title, content: a.content, category: a.category, intent: a.intent, product: a.product, status: a.status === "ARCHIVED" ? "DRAFT" : a.status })}><Icon name="edit" size={16} />Edit (new version)</button>
        </>}>
        {detail.isLoading && <LoadingState />}
        {detail.error && <ErrorState message={(detail.error as Error).message} />}
        {a && <>
          <div className="row"><span className={`badge ${a.status === "ACTIVE" ? "badge-known" : a.status === "DRAFT" ? "badge-uncertain" : "badge-neutral"}`}>{a.status}</span>
            <span className="badge badge-neutral">{a.category}</span><span className="badge badge-neutral">{humanize(a.intent)}</span>
            <span className="badge badge-info">{a.indexed_chunks} indexed chunk(s)</span></div>
          <h3 style={{ fontSize: 24 }}>{a.title}</h3>
          <pre className="content-pre">{a.content}</pre>
          <div className="eyebrow">Version history</div>
          <div className="table-wrap"><table className="table"><thead><tr><th>Version</th><th>Status</th><th>By</th><th>Note</th><th>When</th></tr></thead>
            <tbody>{a.versions.map((v) => <tr key={v.id}><td>v{v.version}</td><td>{v.status}</td><td>{v.created_by}</td><td className="small">{v.change_note}</td><td className="tiny muted">{timeAgo(v.created_at)}</td></tr>)}</tbody></table></div>
        </>}
      </Modal>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={`Edit ${openId} · creates a new version`} wide
        footer={<><button type="button" className="btn btn-ghost" onClick={() => setEditing(null)}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={!valid(editing) || update.isPending} onClick={() => editing && update.mutate(editing)}>Save new version</button></>}>
        {editing && <ArticleForm value={editing} onChange={setEditing} categories={categories} intents={intentOptions} />}
      </Modal>

      <Modal open={!!creating} onClose={() => setCreating(null)} title="New knowledge article" wide
        footer={<><button type="button" className="btn btn-ghost" onClick={() => setCreating(null)}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={!valid(creating) || create.isPending} onClick={() => creating && create.mutate(creating)}>Create article</button></>}>
        {creating && <ArticleForm value={creating} onChange={setCreating} categories={categories} intents={intentOptions} />}
      </Modal>
    </div>
  );
}
