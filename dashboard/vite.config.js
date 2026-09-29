import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the dashboard runs on Vite's port and proxies the API to the
// Node server; in production the Node server serves the built files itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/v1": { target: "http://127.0.0.1:8787", changeOrigin: true } },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: { manualChunks: { map: ["leaflet", "react-leaflet"], charts: ["recharts"] } },
    },
  },
});
