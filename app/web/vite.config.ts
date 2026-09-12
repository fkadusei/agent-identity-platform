import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In production the UI is served by the API (same origin), so requests are
// relative. In dev, proxy the API paths to a locally port-forwarded API.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/demo": "http://localhost:8080",
      "/tasks": "http://localhost:8080",
      "/approvals": "http://localhost:8080",
      "/audit": "http://localhost:8080",
      "/healthz": "http://localhost:8080",
    },
  },
  build: { outDir: "dist" },
});
