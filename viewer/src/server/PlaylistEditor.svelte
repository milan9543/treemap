<script lang="ts">
  // Edit a playlist: its name, the favourites in it (each with its time, in order), the
  // crossfade between them and whether to shuffle. Nothing is saved until Save.
  import { ArrowDown, ArrowUp, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import Button from "../components/ui/Button.svelte";
  import type { Favourite, Playlist, PlaylistFields } from "./api";

  let { playlist, favourites, onsave, ondelete, oncancel }: {
    playlist: Playlist | null; // null: a new one
    favourites: Favourite[];
    onsave: (fields: PlaylistFields) => Promise<void>;
    ondelete?: () => Promise<void>;
    oncancel: () => void;
  } = $props();

  type Row = { key: number; favourite: string; minutes: number };
  let nextKey = 0;
  const start = untrack(() => playlist); // the editor is opened afresh for each playlist
  let name = $state(start?.name ?? "");
  let rows = $state<Row[]>((start?.items ?? []).map((i) => ({
    key: nextKey++, favourite: i.favourite, minutes: Math.round((i.duration_s / 60) * 10) / 10,
  })));
  let crossfade = $state(start?.crossfade_s ?? 3);
  let shuffle = $state(start?.shuffle ?? false);
  let busy = $state(false);

  const byId = $derived(new Map(favourites.map((f) => [f.id, f])));
  const total = $derived(rows.reduce((s, r) => s + (r.minutes || 0), 0));
  const valid = $derived(name.trim().length > 0 && rows.every((r) => r.minutes >= 0.1 && r.minutes <= 1440));

  function add(id: string) {
    if (id) rows = [...rows, { key: nextKey++, favourite: id, minutes: 5 }];
  }

  function move(i: number, by: number) {
    const j = i + by;
    if (j < 0 || j >= rows.length) return;
    const next = [...rows];
    [next[i], next[j]] = [next[j], next[i]];
    rows = next;
  }

  async function save() {
    busy = true;
    try {
      await onsave({
        name: name.trim(),
        items: rows.map((r) => ({ favourite: r.favourite, duration_s: Math.max(5, Math.round(r.minutes * 60)) })),
        crossfade_s: crossfade,
        shuffle,
      });
    } finally {
      busy = false;
    }
  }

  async function remove() {
    if (!ondelete || !confirm(`Delete the playlist "${start?.name}"?`)) return;
    busy = true;
    try {
      await ondelete();
    } finally {
      busy = false;
    }
  }
</script>

<div class="editor">
  <label class="field">
    <span>Name</span>
    <input type="text" maxlength="80" placeholder="Evening" bind:value={name} />
  </label>

  <div class="field">
    <span>Favourites, in turn</span>
    {#if rows.length}
      <ol class="rows">
        {#each rows as r, i (r.key)}
          <li>
            <span class="fav">{byId.get(r.favourite)?.name ?? "(deleted)"}</span>
            <input type="number" min="0.1" max="1440" step="0.5" aria-label="Minutes" bind:value={r.minutes} />
            <span class="muted">min</span>
            <button class="icon" title="Earlier" disabled={i === 0} onclick={() => move(i, -1)}><ArrowUp size={13} /></button>
            <button class="icon" title="Later" disabled={i === rows.length - 1} onclick={() => move(i, 1)}><ArrowDown size={13} /></button>
            <button class="icon bad" title="Take it out" onclick={() => (rows = rows.filter((x) => x.key !== r.key))}><X size={13} /></button>
          </li>
        {/each}
      </ol>
      <p class="muted note">{rows.length} favourite{rows.length === 1 ? "" : "s"}, {Math.round(total * 10) / 10} min a
        round, then it starts again.</p>
    {:else}
      <p class="muted note">None yet: add favourites below.</p>
    {/if}
    {#if favourites.length}
      <select aria-label="Add a favourite" value=""
              onchange={(e) => { add(e.currentTarget.value); e.currentTarget.value = ""; }}>
        <option value="" disabled>+ Add a favourite…</option>
        {#each favourites as f (f.id)}<option value={f.id}>{f.name}</option>{/each}
      </select>
    {/if}
  </div>

  <label class="field">
    <span>Crossfade: <b class="mono">{crossfade} s</b></span>
    <input type="range" min="0" max="30" step="0.5" bind:value={crossfade} />
  </label>
  <label class="check"><input type="checkbox" bind:checked={shuffle} /> Shuffle: a new order each round</label>

  <div class="actions">
    {#if ondelete}<Button variant="danger" size="sm" disabled={busy} onclick={remove}>Delete</Button>{/if}
    <span class="grow"></span>
    <Button size="sm" disabled={busy} onclick={oncancel}>Cancel</Button>
    <Button variant="primary" size="sm" disabled={!valid || busy} onclick={save}>{busy ? "Saving…" : "Save"}</Button>
  </div>
</div>

<style>
  .editor { display: flex; flex-direction: column; gap: var(--s3); }
  .field { display: flex; flex-direction: column; gap: var(--s1); font-size: var(--t-sm); color: var(--muted); }
  .field b { color: var(--text); font-weight: 500; }
  .rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 3px; }
  .rows li { display: grid; grid-template-columns: 1fr 56px auto 24px 24px 24px; gap: var(--s1); align-items: center;
    padding: 3px 3px 3px var(--s2); border: 1px solid var(--border); border-radius: var(--r1); color: var(--text); }
  .fav { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rows input { padding: 2px 4px; text-align: right; }
  .icon { display: grid; place-items: center; height: 24px; background: none; border: 0; border-radius: var(--r1);
    color: var(--muted); cursor: pointer; }
  .icon:hover:not(:disabled) { background: var(--surface-3); color: var(--text); }
  .icon.bad:hover { color: var(--bad); }
  .icon:disabled { opacity: 0.3; cursor: default; }
  .note { margin: 0; font-size: var(--t-xs); }
  .check { display: flex; align-items: center; gap: var(--s2); font-size: var(--t-sm); }
  .actions { display: flex; gap: var(--s2); }
  .grow { flex: 1; }
</style>
