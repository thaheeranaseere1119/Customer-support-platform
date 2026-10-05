import type { ToastItem } from "../hooks/useToast";
import { Icon } from "./Icon";

export function Toast({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  const icon = item.kind === "error" ? "alert" : item.kind === "success" ? "check" : "info";
  return (
    <div className={`toast ${item.kind}`} role={item.kind === "error" ? "alert" : "status"}>
      <Icon name={icon} />
      <span>{item.message}</span>
      <button type="button" onClick={onDismiss} aria-label="Dismiss notification"><Icon name="x" size={16} /></button>
    </div>
  );
}
