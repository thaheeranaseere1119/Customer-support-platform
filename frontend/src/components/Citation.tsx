import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { CitationRef, Source } from "../types/api";
import { humanize, score, splitCitations } from "../utils/format";
import { Modal } from "./Modal";

type Lookup = Record<string, Partial<Source> & CitationRef>;
interface Ctx { open: (id: string) => void; has: (id: string) => boolean }
const SourceContext = createContext<Ctx>({ open: () => undefined, has: () => false });

/** Makes citations clickable: clicking opens the Source Details dialog. */
export function SourceProvider({ sources, citations, children }: { sources: Source[]; citations: CitationRef[]; children: ReactNode }) {
  const [active, setActive] = useState<string | null>(null);
  const lookup = useMemo<Lookup>(() => {
    const map: Lookup = {};
    citations.forEach((c) => { map[c.source_id] = { ...c }; });
    sources.forEach((s) => { map[s.source_id] = { ...map[s.source_id], ...s, score: s.final_score }; });
    return map;
  }, [sources, citations]);
  const open = useCallback((id: string) => setActive(id), []);
  const value = useMemo(() => ({ open, has: (id: string) => id in lookup }), [open, lookup]);
  const src = active ? lookup[active] : null;
  return (
    <SourceContext.Provider value={value}>
      {children}
      <Modal open={!!src} title="Source Details" onClose={() => setActive(null)}>
        {src && <SourceDetails source={src} />}
      </Modal>
    </SourceContext.Provider>
  );
}

function SourceDetails({ source }: { source: Partial<Source> & CitationRef }) {
  const rows: [string, string][] = [
    ["Source ID", source.source_id],
    ["Source type", humanize(source.source_type)],
    ["Title", source.title],
  ];
  if (source.intent) rows.push(["Intent", humanize(source.intent)]);
  if (source.category) rows.push(["Category", source.category]);
  const dup = (source.extra as { duplicate_count?: number } | undefined)?.duplicate_count;
  if (dup && dup > 1) rows.push(["Similar tickets", `${dup} tickets share this resolved template`]);
  return (
    <div className="stack">
      <dl className="kv">{rows.map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      <div>
        <div className="eyebrow" style={{ marginBottom: 6 }}>Relevant excerpt</div>
        <pre className="content-pre">{source.content || source.excerpt}</pre>
      </div>
      <div>
        <div className="eyebrow" style={{ marginBottom: 6 }}>Scores</div>
        <div className="score-row">
          <span className="score-pill">Semantic <b>{score(source.semantic_score)}</b></span>
          <span className="score-pill">Keyword <b>{score(source.keyword_score)}</b></span>
          <span className="score-pill">Metadata <b>{score(source.metadata_score)}</b></span>
          <span className="score-pill">Hybrid <b>{score(source.hybrid_score)}</b></span>
          <span className="score-pill">Reranker <b>{score(source.reranker_score ?? null)}</b></span>
          <span className="score-pill final">Final <b>{score(source.final_score ?? source.score)}</b></span>
        </div>
      </div>
    </div>
  );
}

export function Citation({ id }: { id: string }) {
  const ctx = useContext(SourceContext);
  if (!ctx.has(id)) return <span className="citation missing" title="Source not available">{id}</span>;
  return <button type="button" className="citation" onClick={() => ctx.open(id)} aria-label={`Open source ${id}`}>{id}</button>;
}

/** Renders text with [SOURCE-ID] markers as clickable citations. Never injects HTML. */
export function CitedText({ text }: { text: string }) {
  return (
    <>
      {splitCitations(text).map((part, i) => (part.kind === "text" ? <span key={i}>{part.value}</span> : <Citation key={i} id={part.id} />))}
    </>
  );
}

export function useSourceDetails() {
  return useContext(SourceContext);
}
