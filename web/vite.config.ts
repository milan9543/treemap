import { fileURLToPath } from "node:url";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// `npm run dev` serves the pages with hot reload and forwards the API to a running
// `treemap serve` (port 8765, or TREEMAP_SERVE_PORT). Open /server.html.
const backend = `127.0.0.1:${process.env.TREEMAP_SERVE_PORT ?? 8765}`;

export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: fileURLToPath(new URL("../treemap/web_dist", import.meta.url)),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
    // server.html: the server's page (`treemap serve`); wled.html: the virtual WLED's
    // screen (`treemap sim wled`)
    rollupOptions: {
      input: {
        server: fileURLToPath(new URL("server.html", import.meta.url)),
        wled: fileURLToPath(new URL("wled.html", import.meta.url)),
      },
    },
  },
  server: {
    proxy: { "/api/v2": `http://${backend}` },
  },
});
