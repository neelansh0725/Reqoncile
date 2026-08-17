import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy the API so the browser sees one origin in dev. CORS is configured
    // on the backend too (T057), but proxying means no preflight round-trip
    // on every analyse call.
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true, rewrite: p => p.replace(/^\/api/, "") } },
  },
});
