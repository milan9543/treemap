<script lang="ts">
  // Make a palette, or change one of your own. A built-in palette is the starting point
  // for a new one: its colours are copied, the built-in one stays as it is.
  import { ArrowDown, ArrowUp, Plus, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import Button from "../components/ui/Button.svelte";
  import type { Palette } from "./api";
  import { deletePalette, savePalette, swatch } from "./palettes.svelte";

  let { from, onsaved, ondeleted, oncancel }: {
    from: Palette | null; // the palette to change (or to copy, if built in); null: a new one
    onsaved: (id: string) => void;
    ondeleted: (id: string) => void;
    oncancel: () => void;
  } = $props();

  const MAX = 16;
  const start = untrack(() => from); // the editor is opened afresh for each palette
  const own = start && !start.preset ? start : null;
  let name = $state(start ? (start.preset ? `My ${start.name.toLowerCase()}` : start.name) : "My palette");
  let colors = $state<string[]>(start ? [...start.colors] : ["#ff0000", "#ffffff"]);
  let error = $state<string | null>(null);
  let saving = $state(false);

  function move(i: number, by: number) {
    const j = i + by;
    if (j < 0 || j >= colors.length) return;
    [colors[i], colors[j]] = [colors[j], colors[i]];
  }

  async function save() {
    saving = true;
    try {
      const saved = await savePalette(own?.id ?? null, { name: name.trim(), colors });
      onsaved(saved.id);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  async function remove() {
    if (!own || !confirm(`Delete the palette "${own.name}"? Favourites that use it go back to their effect's own palette.`)) return;
    try {
      await deletePalette(own.id);
      ondeleted(own.id);
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<form class="editor" onsubmit={(e) => { e.preventDefault(); void save(); }}>
  <div class="strip" style:background={swatch(colors)}></div>
  <input type="text" maxlength="80" aria-label="Palette name" bind:value={name} />
  <ol>
    {#each colors as c, i (i)}
      <li>
        <input type="color" value={c} aria-label="Colour {i + 1}" oninput={(e) => (colors[i] = e.currentTarget.value)} />
        <span class="mono">{c}</span>
        <button type="button" class="icon" title="Earlier" disabled={i === 0} onclick={() => move(i, -1)}><ArrowUp size={13} /></button>
        <button type="button" class="icon" title="Later" disabled={i === colors.length - 1} onclick={() => move(i, 1)}><ArrowDown size={13} /></button>
        <button type="button" class="icon bad" title="Remove" disabled={colors.length === 1}
                onclick={() => (colors = colors.filter((_, k) => k !== i))}><X size={13} /></button>
      </li>
    {/each}
  </ol>
  <button type="button" class="add" disabled={colors.length >= MAX}
          onclick={() => (colors = [...colors, colors[colors.length - 1] ?? "#ffffff"])}><Plus size={13} /> Add a colour</button>
  {#if error}<p class="err">{error}</p>{/if}
  <div class="row">
    <Button size="sm" variant="primary" disabled={saving || !name.trim()} onclick={save}>{own ? "Save" : "Save the palette"}</Button>
    <Button size="sm" onclick={oncancel}>Cancel</Button>
    {#if own}<span class="grow"></span><Button size="sm" variant="danger" onclick={remove}>Delete</Button>{/if}
  </div>
</form>

<style>
  .editor { display: flex; flex-direction: column; gap: var(--s2); padding: var(--s2); border: 1px solid var(--border);
    border-radius: var(--r1); background: var(--surface); }
  .strip { height: 14px; border-radius: 4px; border: 1px solid var(--border); }
  ol { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
  li { display: flex; align-items: center; gap: var(--s1); }
  li span { flex: 1; font-size: var(--t-xs); color: var(--muted); }
  li input { width: 36px; height: 22px; padding: 0 2px; }
  .icon { width: 24px; height: 22px; display: grid; place-items: center; background: transparent; border: 0;
    border-radius: var(--r1); color: var(--muted); cursor: pointer; }
  .icon:hover:not(:disabled) { color: var(--text); background: var(--surface-3); }
  .icon.bad:hover:not(:disabled) { color: var(--bad); }
  .icon:disabled { opacity: 0.3; cursor: default; }
  .add { align-self: flex-start; display: inline-flex; align-items: center; gap: 4px; background: none; border: 0;
    padding: 0; color: var(--accent); cursor: pointer; font-size: var(--t-sm); }
  .add:disabled { opacity: 0.4; cursor: default; }
  .err { margin: 0; color: var(--bad); font-size: var(--t-sm); }
  .row { display: flex; gap: var(--s2); align-items: center; }
  .grow { flex: 1; }
</style>
