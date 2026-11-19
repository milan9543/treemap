<script lang="ts">
  import type { Snippet } from "svelte";

  let { title, actions, children, flush = false }: {
    title?: string; actions?: Snippet; children: Snippet; flush?: boolean;
  } = $props();
</script>

<section class="card" class:flush>
  {#if title || actions}
    <header>
      {#if title}<h3>{title}</h3>{/if}
      {#if actions}<div class="actions">{@render actions()}</div>{/if}
    </header>
  {/if}
  {@render children()}
</section>

<style>
  .card { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r2);
    padding: var(--s3) var(--s4); display: flex; flex-direction: column; gap: var(--s3); }
  .flush { padding: 0; overflow: hidden; }
  header { display: flex; align-items: center; justify-content: space-between; gap: var(--s2); }
  h3 { margin: 0; font-size: var(--t-xs); font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.07em; color: var(--muted); }
  .actions { display: flex; gap: var(--s1); }
</style>
