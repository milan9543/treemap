import { fileURLToPath } from "node:url";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// `npm run dev` serves the viewer with hot reload and forwards the API and websockets to
// a running `treemap sim view` (default port 8765; set TREEMAP_PORT to change it). The
// server's page (/server.html) calls /api/v2, which goes to `treemap serve` (port 8765,
// or TREEMAP_SERVE_PORT): run only one of the two on a port.
const backend = `127.0.0.1:${process.env.TREEMAP_PORT ?? 8765}`;
const serveBackend = `127.0.0.1:${process.env.TREEMAP_SERVE_PORT ?? process.env.TREEMAP_PORT ?? 8765}`;

export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: fileURLToPath(new URL("../treemap/sim/viewer_dist", import.meta.url)),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
    // index.html: the viewer (`treemap sim view`); wled.html: the virtual WLED's screen
    // (`treemap sim wled`); server.html: the server's page (`treemap serve`)
    rollupOptions: {
      input: {
        viewer: fileURLToPath(new URL("index.html", import.meta.url)),
        wled: fileURLToPath(new URL("wled.html", import.meta.url)),
        server: fileURLToPath(new URL("server.html", import.meta.url)),
      },
    },
  },
  server: {
    proxy: {
      "/api/v2": `http://${serveBackend}`,
      "/api": `http://${backend}`,
      "/ws": { target: `ws://${backend}`, ws: true },
    },
  },
});
