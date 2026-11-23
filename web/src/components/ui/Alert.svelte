<script lang="ts">
  import { CircleAlert, CircleCheck, Info, TriangleAlert } from "@lucide/svelte";
  import type { Snippet } from "svelte";

  let { tone = "info", children }: { tone?: "info" | "ok" | "warn" | "bad"; children: Snippet } = $props();
  const Icon = $derived({ info: Info, ok: CircleCheck, warn: TriangleAlert, bad: CircleAlert }[tone]);
</script>

<div class="alert {tone}" role={tone === "bad" ? "alert" : "status"}>
  <Icon size={15} />
  <div class="body">{@render children()}</div>
</div>

<style>
  .alert { display: flex; gap: var(--s2); align-items: flex-start; padding: var(--s2) var(--s3);
    border-radius: var(--r1); border: 1px solid; font-size: var(--t-sm); }
  .alert :global(svg) { flex: none; margin-top: 1px; }
  .body { min-width: 0; overflow-wrap: anywhere; }
  .info { background: var(--info-bg); border-color: rgba(110, 168, 255, 0.3); color: #b9d3ff; }
  .ok { background: var(--ok-bg); border-color: rgba(76, 199, 119, 0.3); color: #a6e8bd; }
  .warn { background: var(--warn-bg); border-color: rgba(240, 190, 90, 0.3); color: #f6d99c; }
  .bad { background: var(--bad-bg); border-color: rgba(239, 111, 111, 0.35); color: #f8b4b4; }
</style>
