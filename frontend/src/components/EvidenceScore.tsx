import type { Evidence } from "../types/api";
import { score as fmt } from "../utils/format";
import { StatusBadge } from "./Badges";

const COLORS = { known: "var(--status-known)", uncertain: "var(--status-uncertain)", unknown: "var(--status-unknown)" };
const LABELS: Record<string, string> = { semantic: "Meaning match", reranker: "Re-rank score", intent_match: "Issue type match", source_quality: "Source quality", metadata: "Category match" };

/** Radial gauge with KNOWN / UNKNOWN threshold ticks, plus the weighted components. */
export function EvidenceScore({ evidence, compact }: { evidence: Evidence; compact?: boolean }) {
  const r = 62;
  const c = 2 * Math.PI * r;
  const arc = 0.75;
  const value = Math.max(0, Math.min(1, evidence.score));
  const tick = (t: number) => {
    const angle = (135 + 270 * t) * (Math.PI / 180);
    return { x1: 80 + Math.cos(angle) * 52, y1: 80 + Math.sin(angle) * 52, x2: 80 + Math.cos(angle) * 74, y2: 80 + Math.sin(angle) * 74 };
  };
  const gauge = (
    <svg viewBox="0 0 160 160" width={compact ? 120 : 160} role="img" aria-label={`Confidence ${fmt(value)}, ${evidence.status}`}>
      <circle cx="80" cy="80" r={r} fill="none" stroke="var(--brown-06)" strokeWidth="14" strokeLinecap="round"
        strokeDasharray={`${c * arc} ${c}`} transform="rotate(135 80 80)" />
      <circle cx="80" cy="80" r={r} fill="none" stroke={COLORS[evidence.status]} strokeWidth="14" strokeLinecap="round"
        strokeDasharray={`${c * arc * value} ${c}`} transform="rotate(135 80 80)" />
      {[evidence.thresholds.unknown, evidence.thresholds.known].map((t) => <line key={t} {...tick(t)} stroke="var(--brown)" strokeWidth="2" />)}
      <text x="80" y="84" textAnchor="middle" style={{ font: "800 34px var(--font-display)", fill: "var(--brown)" }}>{fmt(value)}</text>
      <text x="80" y="106" textAnchor="middle" style={{ font: "700 10px var(--font-body)", fill: "var(--brown-60)", letterSpacing: "0.1em" }}>CONFIDENCE</text>
    </svg>
  );
  if (compact) return gauge;
  return (
    <div className="evidence-wrap">
      <div style={{ textAlign: "center" }}>{gauge}<div style={{ marginTop: -6 }}><StatusBadge status={evidence.status} /></div></div>
      <div className="stack-sm">
        <p className="small" style={{ margin: 0 }}>{evidence.status === "known" ? "The assistant found help articles or past cases that clearly match this problem."
          : evidence.status === "uncertain" ? "The assistant found related guidance, but not an exact match."
            : "No help article or past case clearly matches this problem."}</p>
        <details className="details">
          <summary>Why this confidence</summary>
          <div className="details-body stack-sm">
            {Object.entries(evidence.components).map(([k, v]) => (
              <div key={k} className="meter-row">
                <span>{LABELS[k] ?? k}</span>
                <span className="meter"><span style={{ width: `${Math.round(v * 100)}%` }} /></span>
                <b style={{ textAlign: "right" }}>{fmt(v)}</b>
              </div>
            ))}
            <div className="tiny muted">High at {evidence.thresholds.known.toFixed(2)} or above · Low below {evidence.thresholds.unknown.toFixed(2)} · {evidence.relevant_sources} relevant source(s)</div>
          </div>
        </details>
      </div>
    </div>
  );
}
