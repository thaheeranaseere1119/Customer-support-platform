import { useSyncExternalStore } from "react";

const KEY = "support-iq-staff-token";
const EVENT = "support-iq-staff-session";

/** The signed-in staff member's bearer token (admin console only; customers never sign in). */
export function getStaffToken(): string | null {
  try { return window.localStorage.getItem(KEY); } catch { return null; }
}

export function setStaffToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(KEY, token);
    else window.localStorage.removeItem(KEY);
  } catch { /* storage unavailable: the session lasts until reload */ }
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(callback: () => void) {
  window.addEventListener(EVENT, callback);
  window.addEventListener("storage", callback);
  return () => { window.removeEventListener(EVENT, callback); window.removeEventListener("storage", callback); };
}

/** Re-renders when the staff member signs in or out (in this tab or another). */
export function useStaffToken(): string | null {
  return useSyncExternalStore(subscribe, getStaffToken, () => null);
}
