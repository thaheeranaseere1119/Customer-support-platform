import { Icon } from "./Icon";

export function ErrorState({ title = "Something went wrong", message, requestId, onRetry }:
  { title?: string; message: string; requestId?: string | null; onRetry?: () => void }) {
  return (
    <div className="error-state" role="alert">
      <Icon name="alert" size={22} />
      <div className="stack-sm" style={{ flex: 1 }}>
        <strong>{title}</strong>
        <span className="small">{message}</span>
        {requestId && <span className="tiny muted mono">Request ID: {requestId}</span>}
      </div>
      {onRetry && <button type="button" className="btn btn-ghost btn-sm" onClick={onRetry}><Icon name="refresh" size={14} /> Try again</button>}
    </div>
  );
}
