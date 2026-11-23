<script lang="ts">
  // Pick a palette: the built-in ones and your own, each shown as its colours. Your own
  // can be changed here, and a new one made (from scratch or from the one in use).
  import { ChevronDown, Pencil, Plus } from "@lucide/svelte";
  import type { Palette } from "./api";
  import { findPalette, loadPalettes, palettes, swatch } from "./palettes.svelte";
  import PaletteEditor from "./PaletteEditor.svelte";

  let { value, fallback, onchange }: {
    value: string;
    fallback: string; // the effect's own palette, used when the chosen one is gone
    onchange: (id: string) => void;
  } = $props();

  let open = $state(false);
  let editing = $state<{ from: Palette | null } | null>(null);

  const current = $derived(findPalette(value));
  const shown = $derived(current ?? findPalette(fallback));
  const presets = $derived(palettes.list.filter((p) => p.preset));
  const mine = $derived(palettes.list.filter((p) => !p.preset));

  $effect(() => { void loadPalettes(); });

  function choose(id: string) {
    onchange(id);
    open = false;
  }
</script>

<div class="picker">
  <button type="button" class="current" onclick={() => { open = !open; editing = null; }} aria-expanded={open}>
    <span class="strip" style:background={shown ? swatch(shown.colors) : "var(--surface-3)"}></span>
    <span class="name">{current?.name ?? (shown ? `${shown.name} (the chosen one is gone)` : "…")}</span>
    <ChevronDown size={14} />
  </button>

  {#if editing}
    <PaletteEditor from={editing.from} oncancel={() => (editing = null)}
                   onsaved={(id) => { editing = null; choose(id); }}
                   ondeleted={(id) => { editing = null; if (id === value) choose(fallback); }} />
  {:else if open}
    <div class="menu">
      {#if mine.length}
        <h5>Yours</h5>
        {#each mine as p (p.id)}
          <div class="item" class:on={p.id === value}>
            <button type="button" class="pick" onclick={() => choose(p.id)}>
              <span class="strip" style:background={swatch(p.colors)}></span><span class="name">{p.name}</span>
            </button>
            <button type="button" class="icon" title="Change it" onclick={() => (editing = { from: p })}><Pencil size={12} /></button>
          </div>
        {/each}
      {/if}
      <h5>Built in</h5>
      {#each presets as p (p.id)}
        <div class="item" class:on={p.id === value}>
          <button type="button" class="pick" onclick={() => choose(p.id)}>
            <span class="strip" style:background={swatch(p.colors)}></span><span class="name">{p.name}</span>
          </button>
        </div>
      {/each}
      <div class="new">
        <button type="button" class="link" onclick={() => (editing = { from: null })}><Plus size={13} /> New palette</button>
        {#if shown}
          <button type="button" class="link" onclick={() => (editing = { from: shown })}>
            {shown.preset ? `Copy “${shown.name}” to change it` : `Change “${shown.name}”`}</button>
        {/if}
      </div>
      {#if palettes.error}<p class="err">{palettes.error}</p>{/if}
    </div>
  {/if}
</div>

<style>
  .picker { display: flex; flex-direction: column; gap: var(--s1); min-width: 0; }
  .current { display: flex; align-items: center; gap: var(--s2); padding: 4px 6px; background: var(--surface-2);
    border: 1px solid var(--border); border-radius: var(--r1); color: var(--text); cursor: pointer; text-align: left; }
  .current:hover { border-color: var(--border-strong); }
  .strip { flex: none; width: 56px; height: 14px; border-radius: 3px; border: 1px solid rgba(255, 255, 255, 0.12); }
  .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--t-sm); }
  .menu { display: flex; flex-direction: column; gap: 1px; padding: var(--s1); max-height: 320px; overflow-y: auto;
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--r1); }
  h5 { margin: var(--s1) var(--s1) 2px; font-size: var(--t-xs); font-weight: 600; color: var(--faint); }
  .item { display: flex; align-items: center; border-radius: 4px; }
  .item:hover { background: var(--surface-3); }
  .item.on { background: var(--accent-bg); }
  .item.on .name { color: var(--accent); }
  .pick { flex: 1; min-width: 0; display: flex; align-items: center; gap: var(--s2); padding: 4px; background: none;
    border: 0; color: var(--text); cursor: pointer; text-align: left; }
  .icon { width: 26px; height: 24px; display: grid; place-items: center; background: none; border: 0; color: var(--muted);
    cursor: pointer; border-radius: 4px; }
  .icon:hover { color: var(--text); }
  .new { display: flex; flex-wrap: wrap; gap: var(--s1) var(--s3); padding: var(--s2) var(--s1) var(--s1);
    border-top: 1px solid var(--border); margin-top: var(--s1); }
  .link { display: inline-flex; align-items: center; gap: 4px; background: none; border: 0; padding: 0;
    color: var(--accent); cursor: pointer; font-size: var(--t-sm); }
  .err { margin: 0; color: var(--bad); font-size: var(--t-sm); }
</style>
