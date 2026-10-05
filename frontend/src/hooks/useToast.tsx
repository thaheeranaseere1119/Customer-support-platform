import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { Toast } from "../components/Toast";

export type ToastKind = "info" | "success" | "error";
export interface ToastItem { id: number; kind: ToastKind; message: string }

interface ToastApi { notify: (message: string, kind?: ToastKind) => void }
const ToastContext = createContext<ToastApi>({ notify: () => undefined });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);
  const notify = useCallback((message: string, kind: ToastKind = "info") => {
    const id = Date.now() + Math.random();
    setItems((all) => [...all.slice(-3), { id, kind, message }]);
    window.setTimeout(() => dismiss(id), kind === "error" ? 7000 : 4500);
  }, [dismiss]);
  const value = useMemo(() => ({ notify }), [notify]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="region" aria-live="polite" aria-label="Notifications">
        {items.map((t) => <Toast key={t.id} item={t} onDismiss={() => dismiss(t.id)} />)}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
