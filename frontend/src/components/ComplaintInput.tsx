import { useState, type FormEvent } from "react";
import type { Category, InputMode } from "../types/api";
import { CategorySelector } from "./CategorySelector";
import { ExampleComplaint } from "./ExampleComplaint";
import { Icon } from "./Icon";
import { VoiceButton } from "./VoiceButton";

export const GENERAL_EXAMPLES = [
  "My broadband keeps disconnecting",
  "My mobile data is not working",
  "I was charged twice",
  "My SIM is not detected",
  "My calls keep dropping",
];
const MAX = 2000;

interface Props {
  categories: Category[];
  categoryExamples: Record<string, string[]>;
  busy: boolean;
  onSubmit: (complaint: string, guidedCategory: string | null, mode: InputMode) => void;
}

/** Guided + free-text + voice input. All three call the same resolve pipeline. */
export function ComplaintInput({ categories, categoryExamples, busy, onSubmit }: Props) {
  const [text, setText] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [mode, setMode] = useState<InputMode>("free_text");
  const trimmed = text.trim();

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (trimmed.length < 3 || busy) return;
    onSubmit(trimmed, category, category && mode === "free_text" ? "guided" : mode);
  };
  const pick = (value: string) => { setText(value); setMode(category ? "guided" : "free_text"); };
  const examples = category ? categoryExamples[category] ?? [] : GENERAL_EXAMPLES;

  return (
    <form className="composer" onSubmit={submit} aria-label="Customer complaint">
      <div className="eyebrow">Test message</div>
      <h2>What's the customer experiencing?</h2>
      <label htmlFor="complaint" className="sr-only">Complaint</label>
      <textarea id="complaint" className="textarea" placeholder="Describe the issue in your own words..." value={text} maxLength={MAX}
        onChange={(e) => { setText(e.target.value); if (mode === "voice") setMode("free_text"); }}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(); }} />
      <div className="composer-actions">
        <button type="submit" className="btn btn-primary" disabled={busy || trimmed.length < 3}>
          {busy ? <><Icon name="refresh" className="spin" size={16} /> Resolving…</> : <><Icon name="send" size={16} /> Submit Complaint</>}
        </button>
        <VoiceButton disabled={busy} onTranscript={(spoken) => { setText((prev) => (prev ? `${prev} ${spoken}` : spoken)); setMode("voice"); }} />
        {text && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setText("")} disabled={busy}>Clear</button>}
        <span className="char-count">{text.length}/{MAX}{mode === "voice" ? " · voice" : ""}</span>
      </div>

      <div className="stack-sm section-gap">
        <div className="row"><span className="eyebrow">Category (optional)</span>
          {category && <span className="badge badge-yellow">Filter: {category}</span>}</div>
        <CategorySelector categories={categories} selected={category} onSelect={(c) => { setCategory(c); if (c) setMode("guided"); }} />
      </div>
      <div className="stack-sm section-gap">
        <span className="eyebrow">{category ? `${category} examples` : "Try an example"}</span>
        <div className="stack-sm">
          {examples.slice(0, 5).map((ex) => <ExampleComplaint key={ex} text={ex} onPick={pick} />)}
          {examples.length === 0 && <span className="small muted">No examples for this category yet.</span>}
        </div>
      </div>
    </form>
  );
}
