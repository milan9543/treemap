<script lang="ts" generics="T extends string">
  let { options, value, onchange, size = "md" }: {
    options: { value: T; label: string; title?: string; disabled?: boolean }[];
    value: T;
    onchange: (v: T) => void;
    size?: "sm" | "md";
  } = $props();
</script>

<div class="seg {size}" role="radiogroup">
  {#each options as o (o.value)}
    <button type="button" role="radio" aria-checked={o.value === value} class:on={o.value === value}
      disabled={o.disabled} title={o.title} onclick={() => onchange(o.value)}>{o.label}</button>
  {/each}
</div>

<style>
  .seg { display: inline-flex; background: var(--surface-2); border: 1px solid var(--border);
    border-radius: var(--r1); padding: 2px; gap: 2px; }
  button { border: 0; background: transparent; color: var(--muted); border-radius: 4px; cursor: pointer; }
  .md button { padding: 4px 10px; font-size: var(--t-md); }
  .sm button { padding: 2px 8px; font-size: var(--t-sm); }
  button:hover:not(:disabled) { color: var(--text); }
  button.on { background: var(--surface-3); color: var(--text); box-shadow: inset 0 0 0 1px var(--border-strong); }
  button:disabled { opacity: 0.35; cursor: not-allowed; }
</style>
