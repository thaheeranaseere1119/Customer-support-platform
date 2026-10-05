import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { EmergingIssueCard } from "../components/EmergingIssueCard";
import { ErrorState } from "../components/ErrorState";
import { Icon } from "../components/Icon";
import { IntentForm, emptyIntentForm, toPayload, type IntentFormValues } from "../components/IntentManagement";
import { LoadingState } from "../components/LoadingState";
import { Modal } from "../components/Modal";
import { useToast } from "../hooks/useToast";
import { api } from "../services/api";
import type { EmergingIssue } from "../types/api";
import { humanize, score } from "../utils/format";

export function EmergingPage() {
  const qc = useQueryClient();
  const { notify } = useToast();
  const [status, setStatus] = useState("");
  const [members, setMembers] = useState<string | null>(null);
  const [promote, setPromote] = useState<EmergingIssue | null>(null);
  const [form, setForm] = useState<IntentFormValues>(emptyIntentForm());
  const issues = useQuery({ queryKey: ["emerging", status], queryFn: () => api.emergingIssues(status || undefined) });
  const intents = useQuery({ queryKey: ["intents"], queryFn: api.intents });
  const detail = useQuery({ queryKey: ["emerging-detail", members], queryFn: () => api.emergingIssue(members!), enabled: !!members });
  const refresh = () => qc.invalidateQueries();
  const detect = useMutation({ mutationFn: api.detectEmerging, onSuccess: (r) => { notify(`Checked ${r.pool_size} unresolved reports: ${r.created} new and ${r.updated} updated trend(s).`, "success"); refresh(); }, onError: (e: Error) => notify(e.message, "error") });
  const setIssueStatus = useMutation({ mutationFn: ({ id, s }: { id: string; s: "UNDER_REVIEW" | "REJECTED" }) => api.setEmergingStatus(id, s),
    onSuccess: (i) => { notify(`${i.id} → ${i.status.replace("_", " ")}`, "info"); refresh(); }, onError: (e: Error) => notify(e.message, "error") });
  const create = useMutation({ mutationFn: () => api.createIntentFromIssue(promote!.id, toPayload(form)),
    onSuccess: (r) => { notify(`Issue type “${r.intent.name}” created${r.article ? ` with article ${r.article.article_id}` : ""}.`, "success"); setPromote(null); refresh(); },
    onError: (e: Error) => notify(e.message, "error") });

  const openPromote = (issue: EmergingIssue) => {
    setPromote(issue);
    setForm(emptyIntentForm({ name: issue.suggested_intent_name, display_name: humanize(issue.suggested_intent_name), description: issue.pattern_name.replace(/ · /g, " ") + " issue",
      parent_category: intents.data?.categories.some((c) => c.name === issue.suggested_category) ? issue.suggested_category : "",
      examples: issue.example_complaints.join("\n"), keywords: issue.keywords.slice(0, 2).join(", "), resolution_title: `${humanize(issue.suggested_intent_name)}: resolution` }));
  };

  return (
    <div className="stack">
      <div className="page-head"><div><h1>Trending problems</h1><p>New problems that several customers have reported and that no help article covers yet. Review them and turn the real ones into an issue type with a help article.</p></div>
        <div className="row">
          <label className="sr-only" htmlFor="em-status">Status</label>
          <select id="em-status" className="select" style={{ width: "auto" }} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option><option>NEW</option><option value="UNDER_REVIEW">UNDER REVIEW</option><option>APPROVED</option><option>REJECTED</option></select>
          <button type="button" className="btn btn-primary" disabled={detect.isPending} onClick={() => detect.mutate()}><Icon name="refresh" size={16} className={detect.isPending ? "spin" : undefined} />Check for new trends</button>
        </div></div>
      {issues.isLoading && <LoadingState rows={3} />}
      {issues.error && <ErrorState message={(issues.error as Error).message} onRetry={() => issues.refetch()} />}
      {issues.data && issues.data.length === 0 && <div className="card empty-state"><div className="empty-illustration"><Icon name="radar" size={44} /></div><p className="muted">Nothing trending right now. When several customers report a similar new problem, it shows up here.</p></div>}
      <div className="grid grid-3">
        {issues.data?.map((i) => (
          <EmergingIssueCard key={i.id} issue={i} onView={() => setMembers(i.id)} onReview={() => setIssueStatus.mutate({ id: i.id, s: "UNDER_REVIEW" })}
            onReject={() => setIssueStatus.mutate({ id: i.id, s: "REJECTED" })} onCreateIntent={() => openPromote(i)} />
        ))}
      </div>

      <Modal open={!!members} onClose={() => setMembers(null)} title={detail.data ? detail.data.pattern_name : "Cluster members"} wide>
        {detail.isLoading && <LoadingState />}
        {detail.data && <>
          <p className="small muted">{detail.data.description}</p>
          <div className="table-wrap"><table className="table"><thead><tr><th>Member</th><th>Complaint</th><th>Similarity</th><th>Evidence</th><th>Weight</th></tr></thead>
            <tbody>{detail.data.members?.map((m) => <tr key={m.member_id}><td className="mono">{m.member_id}<div className="tiny muted">{m.member_type}</div></td><td>{m.complaint}</td>
              <td>{score(m.similarity)}</td><td>{score(m.evidence_score)}</td><td>{m.weight}</td></tr>)}</tbody></table></div>
        </>}
      </Modal>

      <Modal open={!!promote} onClose={() => setPromote(null)} title="Create an issue type" wide>
        <p className="small muted">This adds a new issue type with its example messages and publishes the help article below, so the assistant can recognise and answer this problem straight away.</p>
        <IntentForm categories={intents.data?.categories ?? []} values={form} onChange={setForm} onSubmit={() => create.mutate()} busy={create.isPending} submitLabel="Create issue type" />
      </Modal>
    </div>
  );
}
