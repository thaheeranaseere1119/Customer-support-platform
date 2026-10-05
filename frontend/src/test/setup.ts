import "@testing-library/jest-dom/vitest";

// Node 25 exposes an experimental global localStorage that shadows jsdom's; use a
// spec-compatible in-memory Storage so tests are deterministic on every Node version.
const store = new Map<string, string>();
const memoryStorage: Storage = {
  getItem: (key) => store.get(key) ?? null,
  setItem: (key, value) => { store.set(key, String(value)); },
  removeItem: (key) => { store.delete(key); },
  clear: () => store.clear(),
  key: (index) => [...store.keys()][index] ?? null,
  get length() { return store.size; },
};
Object.defineProperty(window, "localStorage", { value: memoryStorage, configurable: true });
Object.defineProperty(globalThis, "localStorage", { value: memoryStorage, configurable: true });

// jsdom does not implement scrolling.
window.scrollTo = () => undefined;
Element.prototype.scrollIntoView = () => undefined;
