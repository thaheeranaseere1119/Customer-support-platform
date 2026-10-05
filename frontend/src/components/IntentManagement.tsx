import { useState, type FormEvent } from "react";
import type { Category, Intent, IntentCreatePayload } from "../types/api";
import { humanize, linesToList, num } from "../utils/format";

export interface IntentFormValues {
  name: string; display_name: string; description: string; parent_category: string; examples: string; keywords: string;
  resolution_title: string; resolution_steps: string;
}

export const emptyIntentForm = (overrides: Partial<IntentFormValues> = {}): IntentFormValues => ({
  name: "", display_name: "", description: "", parent_category: "", examples: "", keywords: "", resolution_title: "",
  resolution_steps: "", ...overrides,
});

export function toPayload(v: IntentFormValues): IntentCreatePayload {
  return {
    name: v.name.trim(), display_name: v.display_name.trim() || undefined, description: v.description.trim(),
    parent_category: v.parent_category, example_complaints: linesToList(v.examples),
    keywords: v.keywords.split(",").map((k) => k.trim()).filter(Boolean), resolution_title: v.resolution_title.trim() || undefined,
    resolution_steps: linesToList(v.resolution_steps),
  };
}

/** Shared form used for manual intent creation and for promoting an emerging issue. */
export function IntentForm({ categories, values, onChange, onSubmit, busy, submitLabel }:
  { categories: Category[]; values: IntentFormValues; onChange: (v: IntentFormValues) => void; onSubmit: () => void; busy: boolean; submitLabel: string }) {
  const set = (k: keyof IntentFormValues) => (e: { target: { value: string } }) => onChange({ ...values, [k]: e.target.value });
  const valid = /^[a-z][a-z0-9_]{2,60}$/.test(values.name.trim()) && values.description.trim().length >= 5 && !!values.parent_category && linesToList(values.examples).length > 0;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid && !busy) onSubmit(); };
  return (
    <form className="stack" onSubmit={submit}>
      <div className="grid grid-2">
        <div className="field"><label htmlFor="i-name">Issue type ID</label><input id="i-name" className="input mono" value={values.name} onChange={set("name")} placeholder="visual_voicemail_transcription" />
          <span className="field-hint">snake_case: lowercase letters, digits, underscores</span></div>
        <div className="field"><label htmlFor="i-display">Display name</label><input id="i-display" className="input" value={values.display_name} onChange={set("display_name")} /></div>
      </div>
      <div className="field"><label htmlFor="i-desc">Description</label><input id="i-desc" className="input" value={values.description} onChange={set("description")} /></div>
      <div className="grid grid-2">
        <div className="field"><label htmlFor="i-cat">Parent category</label>
          <select id="i-cat" className="select" value={values.parent_category} onChange={set("parent_category")}>
            <option value="">Select…</option>{categories.map((c) => <option key={c.name} value={c.name}>{c.parent_name ? `${c.parent_name} › ${c.name}` : c.name}</option>)}
          </select></div>
        <div className="field"><label htmlFor="i-kw">Keywords (comma separated)</label><input id="i-kw" className="input" value={values.keywords} onChange={set("keywords")} placeholder="visual voicemail, voicemail transcription" /></div>
      </div>
      <div className="field"><label htmlFor="i-ex">Example complaints (one per line)</label><textarea id="i-ex" className="textarea" style={{ minHeight: 90 }} value={values.examples} onChange={set("examples")} /></div>
      <div className="field"><label htmlFor="i-rt">Help article title</label><input id="i-rt" className="input" value={values.resolution_title} onChange={set("resolution_title")} /></div>
      <div className="field"><label htmlFor="i-rs">Fix steps (one per line, published as a help article)</label>
        <textarea id="i-rs" className="textarea" style={{ minHeight: 90 }} value={values.resolution_steps} onChange={set("resolution_steps")} /></div>
      <div className="row"><span className="spacer" />
        {!valid && <span className="tiny muted">Name, description, category and at least one example are required.</span>}
        <button type="submit" className="btn btn-primary" disabled={!valid || busy}>{busy ? "Saving…" : submitLabel}</button></div>
    </form>
  );
}

export function IntentManagement({ intents, categories }: { intents: Intent[]; categories: Category[] }) {
  const [filter, setFilter] = useState("");
  const shown = intents.filter((i) => !filter || i.support_category === filter || categories.find((c) => c.name === i.support_category)?.parent_name === filter);
  return (
    <div className="stack">
      <div className="toolbar">
        <label className="sr-only" htmlFor="intent-filter">Category</label>
        <select id="intent-filter" className="select" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All categories ({intents.length})</option>
          {categories.filter((c) => !c.parent_name).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Issue type</th><th>Category</th><th>Group</th><th>Keywords</th><th>Past tickets</th><th>Cases</th><th>Articles</th><th>Added by</th></tr></thead>
          <tbody>
            {shown.map((i) => (
              <tr key={i.name}>
                <td><b>{i.display_name}</b><div className="tiny mono muted">{i.name}</div></td>
                <td>{i.support_category}</td>
                <td className="tiny">{i.domain_category}</td>
                <td className="tiny" style={{ maxWidth: 260 }}><span className="clamp-2">{i.keywords.join(", ")}</span></td>
                <td>{num(i.ticket_count)}</td><td>{num(i.case_count)}</td>
                <td>{i.active_articles ? <span className="badge badge-known">{i.active_articles}</span> : <span className="badge badge-uncertain">0</span>}</td>
                <td><span className={`badge ${i.origin === "dataset" ? "badge-neutral" : "badge-yellow"}`}>{humanize(i.origin)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
