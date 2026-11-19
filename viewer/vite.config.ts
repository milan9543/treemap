import { fileURLToPath } from "node:url";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// `npm run dev` serves the viewer with hot reload and forwards the API and websockets to
// a running `treemap sim view` (default port 8765; set TREEMAP_PORT to change it).
const backend = `127.0.0.1:${process.env.TREEMAP_PORT ?? 8765}`;

export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: fileURLToPath(new URL("../treemap/sim/viewer_dist", import.meta.url)),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
  },
  server: {
    proxy: {
      "/api": `http://${backend}`,
      "/ws": { target: `ws://${backend}`, ws: true },
    },
  },
});
