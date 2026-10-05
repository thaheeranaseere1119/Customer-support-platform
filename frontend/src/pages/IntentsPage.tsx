import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorState } from "../components/ErrorState";
import { CATEGORY_ICONS, Icon } from "../components/Icon";
import { IntentForm, IntentManagement, emptyIntentForm, toPayload } from "../components/IntentManagement";
import { LoadingState } from "../components/LoadingState";
import { Modal } from "../components/Modal";
import { useToast } from "../hooks/useToast";
import { api } from "../services/api";

export function IntentsPage() {
  const qc = useQueryClient();
  const { notify } = useToast();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyIntentForm());
  const q = useQuery({ queryKey: ["intents"], queryFn: api.intents });
  const create = useMutation({ mutationFn: () => api.createIntent(toPayload(form)),
    onSuccess: (r) => { notify(`Issue type “${r.intent.name}” added. The assistant can recognise it now.`, "success"); setOpen(false); setForm(emptyIntentForm()); qc.invalidateQueries(); },
    onError: (e: Error) => notify(e.message, "error") });
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Issue types</h1><p>How customer problems are categorised. Each type has keywords and example messages the assistant uses to recognise it.</p></div>
        <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}><Icon name="plus" size={16} />Create issue type</button></div>
      {q.isLoading && <LoadingState rows={6} />}
      {q.error && <ErrorState message={(q.error as Error).message} onRetry={() => q.refetch()} />}
      {q.data && <>
        <section className="card card-cream"><div className="eyebrow" style={{ marginBottom: 12 }}>Categories</div>
          <div className="category-grid">{q.data.categories.map((c) => (
            <span key={c.name} className="category-chip" style={{ cursor: "default", background: "var(--white)" }} title={c.description}>
              <Icon name={CATEGORY_ICONS[c.name] ?? "tag"} size={16} />{c.parent_name ? `${c.parent_name} › ` : ""}{c.name}</span>))}</div>
        </section>
        <section className="card"><IntentManagement intents={q.data.intents} categories={q.data.categories} /></section>
      </>}
      <Modal open={open} onClose={() => setOpen(false)} title="Create issue type" wide>
        <IntentForm categories={q.data?.categories ?? []} values={form} onChange={setForm} onSubmit={() => create.mutate()} busy={create.isPending} submitLabel="Create issue type" />
      </Modal>
    </div>
  );
}
