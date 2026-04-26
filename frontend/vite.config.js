import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// REST і WS проксяться на FastAPI (uvicorn :8000) у dev-режимі.
// Так фронтенд може звертатися до /jobs, /workflows, /ws/jobs/* без CORS-стрибків.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/jobs": "http://localhost:8000",
      "/workflows": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/api": "http://localhost:8000",
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
