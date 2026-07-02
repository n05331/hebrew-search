import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base יחסי כדי שהנכסים יטענו גם כשמוגשים מ-FastAPI וגם בגרסת ה-EXE
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8756",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
