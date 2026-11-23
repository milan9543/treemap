<script lang="ts">
  // A titled group of controls inside a card, with an optional control in its heading
  // (a switch that turns the group on, or a choice that changes what's below).
  import type { Snippet } from "svelte";

  let { title, control, children }: { title: string; control?: Snippet; children?: Snippet } = $props();
</script>

<div class="section">
  <div class="head">
    <h4>{title}</h4>
    {#if control}{@render control()}{/if}
  </div>
  {#if children}{@render children()}{/if}
</div>

<style>
  .section { display: flex; flex-direction: column; gap: var(--s2); padding-top: var(--s3);
    border-top: 1px solid var(--border); }
  .head { display: flex; align-items: center; justify-content: space-between; gap: var(--s2); min-height: 24px; }
  h4 { margin: 0; font-size: var(--t-xs); font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em;
    color: var(--faint); }
</style>
