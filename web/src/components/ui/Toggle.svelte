<script lang="ts">
  import type { Snippet } from "svelte";

  let { checked = $bindable(false), title, onchange, children }: {
    checked?: boolean; title?: string; onchange?: (v: boolean) => void; children?: Snippet;
  } = $props();
</script>

<label class="toggle" {title}>
  <input type="checkbox" bind:checked onchange={() => onchange?.(checked)} />
  <span class="track"><span class="knob"></span></span>
  {#if children}<span class="label">{@render children()}</span>{/if}
</label>

<style>
  .toggle { display: inline-flex; align-items: center; gap: var(--s2); cursor: pointer; user-select: none; }
  input { position: absolute; opacity: 0; width: 0; height: 0; }
  .track { width: 28px; height: 16px; border-radius: 10px; background: var(--surface-3);
    border: 1px solid var(--border-strong); position: relative; flex: none; transition: background 0.15s; }
  .knob { position: absolute; top: 2px; left: 2px; width: 10px; height: 10px; border-radius: 50%;
    background: var(--muted); transition: transform 0.15s, background 0.15s; }
  input:checked + .track { background: var(--accent-bg); border-color: var(--accent-border); }
  input:checked + .track .knob { transform: translateX(12px); background: var(--accent); }
  input:focus-visible + .track { outline: 2px solid var(--accent-border); outline-offset: 1px; }
  .label { font-size: var(--t-md); }
</style>
