import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ModeBadge } from "../components/Badges";
import { ErrorState } from "../components/ErrorState";
import { Icon } from "../components/Icon";
import { LoadingState } from "../components/LoadingState";
import { useSpeechRecognition } from "../hooks/useSpeechRecognition";
import { useAgentName } from "../hooks/useAgentName";
import { useToast } from "../hooks/useToast";
import { api } from "../services/api";
import type { SettingsResponse } from "../types/api";
import { humanize } from "../utils/format";

type Tunable = SettingsResponse["tunable"];
const FIELDS: { key: keyof Tunable; label: string; step: number; min: number; max: number }[] = [
  { key: "known_threshold", label: "KNOWN threshold", step: 0.01, min: 0, max: 1 },
  { key: "unknown_threshold", label: "UNKNOWN threshold", step: 0.01, min: 0, max: 1 },
  { key: "semantic_weight", label: "Semantic weight", step: 0.05, min: 0, max: 1 },
  { key: "keyword_weight", label: "Keyword weight", step: 0.05, min: 0, max: 1 },
  { key: "metadata_weight", label: "Metadata weight", step: 0.05, min: 0, max: 1 },
  { key: "top_k", label: "Top K", step: 1, min: 1, max: 50 },
  { key: "max_resolution_attempts", label: "Max resolution attempts", step: 1, min: 1, max: 10 },
  { key: "emerging_similarity_threshold", label: "Emerging cluster similarity", step: 0.01, min: 0.3, max: 0.99 },
  { key: "emerging_min_cluster_size", label: "Emerging min occurrences", step: 1, min: 2, max: 1000 },
];

function ProfileCard() {
  const [name, setName] = useAgentName();
  const [draft, setDraft] = useState(name);
  const { notify } = useToast();
  return (
    <div className="grid grid-2">
      <section className="card">
        <div className="card-header"><h2 className="card-title">Your profile</h2></div>
        <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); setName(draft); notify("Profile saved.", "success"); }}>
          <div className="field"><label htmlFor="profile-name">Name shown to customers</label>
            <input id="profile-name" className="input" value={draft} maxLength={80} onChange={(e) => setDraft(e.target.value)} />
            <span className="field-hint">Customers see this name on your replies in the live inbox.</span></div>
          <div><button type="submit" className="btn btn-primary btn-sm" disabled={!draft.trim() || draft.trim() === name}>Save</button></div>
        </form>
      </section>
      <section className="card">
        <div className="card-header"><h2 className="card-title">About this workspace</h2></div>
        <p className="small" style={{ margin: 0 }}>This is a demo workspace. Tickets, customers and help articles are sample data, not real customer records.</p>
      </section>
    </div>
  );
}

export function SettingsPage({ sessionId, onNewSession }: { sessionId: string; onNewSession: () => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const voice = useSpeechRecognition(() => undefined);
  const [form, setForm] = useState<Tunable | null>(null);
  useEffect(() => { if (settings.data) setForm(settings.data.tunable); }, [settings.data]);
  const save = useMutation({ mutationFn: (t: Tunable) => api.updateSettings(t),
    onSuccess: (s) => { qc.setQueryData(["settings"], s); notify("Settings saved and applied to the running pipeline.", "success"); },
    onError: (e: Error) => notify(e.message, "error") });
  const weightSum = form ? form.semantic_weight + form.keyword_weight + form.metadata_weight : 1;
  const thresholdsOk = form ? form.unknown_threshold < form.known_threshold : true;
  const valid = Math.abs(weightSum - 1) < 0.001 && thresholdsOk;
  const s = settings.data;
  const h = health.data;
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Settings</h1><p>How the assistant behaves, and your profile.</p></div></div>
      {(settings.isLoading || health.isLoading) && <LoadingState />}
      {settings.error && <ErrorState message={(settings.error as Error).message} onRetry={() => settings.refetch()} />}
      <ProfileCard />
      {s && h && (
        <div className="grid grid-2">
          <section className="card"><div className="card-header"><div><div className="eyebrow">Runtime</div><h2 className="card-title">Mode & models</h2></div><ModeBadge mode={s.mode} /></div>
            <dl className="kv">
              <dt>Mode</dt><dd>{s.demo_mode ? "DEMO MODE: deterministic, evidence-only templates (no API key required)" : "AI MODE: Gemini generation behind the grounding guard"}</dd>
              <dt>LLM provider</dt><dd>{humanize(s.llm.provider)} · Gemini key {s.llm.gemini_configured ? "configured" : "not configured"} ({s.llm.gemini_model})</dd>
              <dt>Enable AI mode</dt><dd>Set <span className="mono">GEMINI_API_KEY</span> and <span className="mono">DEMO_MODE=false</span> in the backend <span className="mono">.env</span>, then restart.</dd>
              <dt>Embeddings</dt><dd>{s.embedding.model} · {humanize(s.embedding.backend)} · {s.embedding.dimension}d</dd>
              <dt>Reranker</dt><dd>{s.reranker.model} · {s.reranker.loaded ? "loaded" : "fallback to hybrid score"}</dd>
              <dt>Database</dt><dd>{humanize(h.database.backend)}{h.database.using_fallback ? " (fallback)" : ""} · pgvector {h.database.pgvector ? "on" : "off (in-memory cosine)"}</dd>
              <dt>Vector index</dt><dd>{h.index.documents} documents · version {h.index.index_version}</dd>
              <dt>Voice input</dt><dd>{voice.supported ? "Web Speech API available" : "Voice input is not supported in this browser."}</dd>
              <dt>Session</dt><dd className="mono">{sessionId}</dd>
            </dl>
            <div className="row section-gap"><button type="button" className="btn btn-ghost btn-sm" onClick={() => { onNewSession(); notify("New session started.", "info"); }}><Icon name="refresh" size={14} />Start new session</button></div>
            <div className="section-gap"><div className="eyebrow" style={{ marginBottom: 8 }}>Evidence weights (fixed in config)</div>
              <div className="score-row">{Object.entries(s.evidence_weights).map(([k, v]) => <span key={k} className="score-pill">{humanize(k)} <b>{v.toFixed(2)}</b></span>)}</div></div>
          </section>
          <section className="card"><div className="card-header"><div><div className="eyebrow">Retrieval & workflow</div><h2 className="card-title">Tunable parameters</h2></div></div>
            {form && <form className="stack" onSubmit={(e) => { e.preventDefault(); if (valid) save.mutate(form); }}>
              <div className="grid grid-2">{FIELDS.map((f) => (
                <div key={f.key} className="field"><label htmlFor={`set-${f.key}`}>{f.label}</label>
                  <input id={`set-${f.key}`} type="number" className="input" step={f.step} min={f.min} max={f.max} value={form[f.key] as number}
                    onChange={(e) => setForm({ ...form, [f.key]: Number(e.target.value) })} /></div>))}</div>
              <label className="switch"><input type="checkbox" checked={form.reranker_enabled} onChange={(e) => setForm({ ...form, reranker_enabled: e.target.checked })} />Cross-encoder reranker enabled</label>
              {!valid && <div className="warning-box">{!thresholdsOk ? "UNKNOWN threshold must be lower than KNOWN threshold. " : ""}{Math.abs(weightSum - 1) >= 0.001 ? `Retrieval weights must sum to 1.00 (currently ${weightSum.toFixed(2)}).` : ""}</div>}
              <div className="row"><span className="spacer" />
                <button type="button" className="btn btn-ghost" onClick={() => setForm(s.tunable)}>Reset</button>
                <button type="submit" className="btn btn-primary" disabled={!valid || save.isPending}>Save settings</button></div>
            </form>}
          </section>
        </div>
      )}
    </div>
  );
}
