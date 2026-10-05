/// <reference types="vitest" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const target = env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    server: { port: 5173, host: "127.0.0.1", proxy: { "/api": { target, changeOrigin: true } } },
    preview: { port: 4173, proxy: { "/api": { target, changeOrigin: true } } },
    test: { environment: "jsdom", globals: true, setupFiles: ["./src/test/setup.ts"], css: false },
  };
});
