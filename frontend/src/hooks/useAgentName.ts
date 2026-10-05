import { useCallback, useSyncExternalStore } from "react";

const KEY = "telecom-agent-name";
const EVENT = "telecom-agent-name-change";
const DEFAULT = "Support agent";

function read(): string {
  try { return window.localStorage.getItem(KEY) || DEFAULT; } catch { return DEFAULT; }
}
function subscribe(callback: () => void) {
  window.addEventListener(EVENT, callback);
  window.addEventListener("storage", callback);
  return () => { window.removeEventListener(EVENT, callback); window.removeEventListener("storage", callback); };
}

/** The signed-in agent's display name (shown to customers on replies). Shared by the top bar and the inbox. */
export function useAgentName(): [string, (name: string) => void] {
  const name = useSyncExternalStore(subscribe, read, () => DEFAULT);
  const setName = useCallback((value: string) => {
    try { window.localStorage.setItem(KEY, value.trim() || DEFAULT); } catch { /* storage unavailable */ }
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [name, setName];
}

export const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("") || "SA";
