import { useCallback, useState } from "react";

const KEY = "telecom-support-session-id";

function generate(): string {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID().slice(0, 12) : Math.random().toString(36).slice(2, 14);
  return `session-${random}`;
}

function read(): string {
  try {
    const existing = window.localStorage.getItem(KEY);
    if (existing && /^[A-Za-z0-9_\-:.]{1,80}$/.test(existing)) return existing;
    const fresh = generate();
    window.localStorage.setItem(KEY, fresh);
    return fresh;
  } catch {
    return generate();
  }
}

/** Per-browser support session used for conversation memory. */
export function useSession() {
  const [sessionId, setSessionId] = useState<string>(read);
  const reset = useCallback(() => {
    const fresh = generate();
    try {
      window.localStorage.setItem(KEY, fresh);
    } catch {
      /* storage unavailable: keep in memory only */
    }
    setSessionId(fresh);
    return fresh;
  }, []);
  return { sessionId, reset };
}
