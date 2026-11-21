import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// The scan page. `npm run build` writes dist/, which Cloudflare Pages serves over HTTPS.
// `npm run dev` serves it on http://localhost:5173, an origin `treemap serve` allows by
// default; open it with ?server=http://127.0.0.1:8765.
export default defineConfig({
  plugins: [svelte()],
  server: { port: 5173, strictPort: true },
  worker: { format: "es" },
});
