<script lang="ts">
  import type { Snippet } from "svelte";

  let { trigger, children, align = "left", up = false }: {
    trigger: Snippet<[() => void, boolean]>; children: Snippet; align?: "left" | "right"; up?: boolean;
  } = $props();
  let open = $state(false);
  let root: HTMLElement;
  const toggle = () => { open = !open; };

  function outside(e: PointerEvent) {
    if (open && root && !root.contains(e.target as Node)) open = false;
  }
</script>

<svelte:window onpointerdown={outside} onkeydown={(e) => { if (e.key === "Escape") open = false; }} />

<div class="pop" bind:this={root}>
  {@render trigger(toggle, open)}
  {#if open}
    <div class="panel {align}" class:up>{@render children()}</div>
  {/if}
</div>

<style>
  .pop { position: relative; display: inline-block; }
  .panel { position: absolute; top: calc(100% + 6px); z-index: 20; min-width: 200px;
    background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--r2);
    box-shadow: var(--shadow); padding: var(--s2); display: flex; flex-direction: column; gap: var(--s1); }
  .panel.up { top: auto; bottom: calc(100% + 6px); }
  .left { left: 0; }
  .right { right: 0; }
</style>
