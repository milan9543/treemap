<script lang="ts">
  import type { Snippet } from "svelte";

  let { label, hint, children }: { label: string; hint?: string; children: Snippet } = $props();
</script>

<label class="field" title={hint}>
  <span>{label}</span>
  {@render children()}
</label>

<style>
  .field { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  span { font-size: var(--t-xs); color: var(--muted); }
</style>
