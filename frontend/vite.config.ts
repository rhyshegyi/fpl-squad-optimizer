import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin proxy — the React app calls /api/... and vite forwards to
    // the FastAPI backend, so we avoid CORS in dev and keep prod code simple.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
