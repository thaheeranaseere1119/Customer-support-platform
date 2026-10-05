import type { EvidenceStatus, Sentiment, Severity } from "../types/api";
import { humanize, statusLabel } from "../utils/format";
import { Icon } from "./Icon";

export function IntentBadge({ intent, display }: { intent: string; display?: string }) {
  const unknown = intent === "unknown";
  return (
    <span className={`badge ${unknown ? "badge-unknown" : "badge-brown"}`} title={intent}>
      <Icon name={unknown ? "alert" : "target"} size={13} />{display || humanize(intent)}
    </span>
  );
}

const SEVERITY_CLASS: Record<Severity, string> = { low: "badge-known", medium: "badge-info", high: "badge-uncertain", critical: "badge-unknown" };

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`badge ${SEVERITY_CLASS[severity]}`}><Icon name="bolt" size={12} />{severity.toUpperCase()}</span>;
}

const SENTIMENT_CLASS: Record<Sentiment, string> = {
  positive: "badge-known", neutral: "badge-neutral", negative: "badge-uncertain", frustrated: "badge-unknown", urgent: "badge-unknown",
};

export function SentimentBadge({ sentiment }: { sentiment: Sentiment }) {
  return <span className={`badge ${SENTIMENT_CLASS[sentiment]}`}><Icon name="chat" size={12} />{sentiment.toUpperCase()}</span>;
}

export function StatusBadge({ status }: { status: EvidenceStatus }) {
  const icon = status === "known" ? "check" : status === "uncertain" ? "info" : "alert";
  return <span className={`badge badge-${status}`}><Icon name={icon} size={12} />{statusLabel[status]}</span>;
}

export function ModeBadge({ mode }: { mode: string }) {
  const ai = mode === "AI MODE";
  return <span className={`badge mode-badge ${ai ? "ai" : ""}`} title={ai ? "Gemini LLM enabled" : "Running without external LLM: deterministic grounded templates"}>{mode}</span>;
}
