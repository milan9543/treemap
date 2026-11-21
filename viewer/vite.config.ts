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
    // index.html: the viewer (`treemap sim view`); wled.html: the virtual WLED's screen
    // (`treemap sim wled`)
    rollupOptions: {
      input: {
        viewer: fileURLToPath(new URL("index.html", import.meta.url)),
        wled: fileURLToPath(new URL("wled.html", import.meta.url)),
      },
    },
  },
  server: {
    proxy: {
      "/api": `http://${backend}`,
      "/ws": { target: `ws://${backend}`, ws: true },
    },
  },
});
