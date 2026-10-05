import { Icon } from "./Icon";

export function LoadingState({ label = "Loading…", rows = 0 }: { label?: string; rows?: number }) {
  if (rows > 0) {
    return (
      <div className="stack-sm" aria-busy="true" aria-label={label}>
        {Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton" style={{ height: 44 }} />)}
      </div>
    );
  }
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <Icon name="refresh" className="spin" /> <span>{label}</span>
    </div>
  );
}
