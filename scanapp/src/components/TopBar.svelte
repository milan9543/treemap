<script lang="ts">
  import { app, type Screen } from "../lib/state.svelte";

  let { title, back, step }: { title: string; back?: Screen; step?: string } = $props();
  const host = $derived(app.server.replace(/^https?:\/\//, ""));
</script>

<header class="top">
  {#if back}
    <button class="back" aria-label="Back" onclick={() => (app.screen = back)}>
      <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
        <path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2.2"
              stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>
  {/if}
  <div class="titles">
    {#if step}<div class="step">{step}</div>{/if}
    <h1>{title}</h1>
  </div>
  <div class="host mono" title={app.server}>{host}</div>
</header>

<style>
  .top { display: flex; align-items: center; gap: 8px; margin: 0 0 8px; }
  .back {
    min-height: 40px; width: 40px; padding: 0; display: grid; place-items: center;
    border: 0; background: none; color: var(--text); margin-left: -8px;
  }
  .titles { flex: 1 1 auto; min-width: 0; }
  .step { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  h1 { margin: 0; }
  .host { font-size: 12px; color: var(--faint); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 40%; }
</style>
