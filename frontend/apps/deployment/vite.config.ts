import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  // Served under /deployment/ in production, both by nginx and by the backend.
  base: "/deployment/",
  plugins: [react(), tailwindcss()],
  resolve: {
    // Order matters: the exact theme.css entry has to win over the package
    // root, which is a file rather than a directory.
    alias: {
      "@portal/shared/theme.css": fileURLToPath(
        new URL("../../packages/shared/src/theme.css", import.meta.url),
      ),
      "@portal/shared": fileURLToPath(
        new URL("../../packages/shared/src/index.ts", import.meta.url),
      ),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // The dev server proxies the API, including SSE, so the app sees one
      // origin just like it does in production.
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // Buffering would defeat the point of a log stream.
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            if (proxyRes.headers["content-type"]?.includes("text/event-stream")) {
              proxyRes.headers["cache-control"] = "no-cache";
            }
          });
        },
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});