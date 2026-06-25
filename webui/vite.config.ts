import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During development, proxy /api/* to the FastAPI backend on :8000.
// In production, FastAPI serves the built bundle from webui/dist/.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
