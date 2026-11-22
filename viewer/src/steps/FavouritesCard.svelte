<script lang="ts">
  import { Pencil, Trash2 } from "@lucide/svelte";
  import Alert from "../components/ui/Alert.svelte";
  import Card from "../components/ui/Card.svelte";
  import { runEffect } from "../lib/actions";
  import { favourites, type Favourite } from "../lib/favourites.svelte";
  import { app } from "../lib/state.svelte";

  const labels = $derived(new Map((app.effects?.effects ?? []).map((e) => [e.name, e.label])));
  const current = $derived(favourites.find(app.engine.running, app.engine.params));
  let editing = $state<string | null>(null);
  let draft = $state("");

  function play(f: Favourite) {
    runEffect(f.effect, f.params);
    favourites.lastPlayed = f.id;
  }
  function startRename(f: Favourite) {
    editing = f.id;
    draft = f.name;
  }
  function finishRename(save: boolean) {
    if (save && editing) favourites.rename(editing, draft);
    editing = null;
  }
  const focus = (el: HTMLInputElement) => { el.focus(); el.select(); };
</script>

<Card title="Favourites">
  {#if favourites.list.length}
    <ul>
      {#each favourites.list as f (f.id)}
        {@const label = labels.get(f.effect)}
        <li class:on={current?.id === f.id}>
          {#if editing === f.id}
            <input class="name" bind:value={draft} use:focus aria-label="Favourite name"
              onkeydown={(e) => { if (e.key === "Enter") finishRename(true); if (e.key === "Escape") finishRename(false); }}
              onblur={() => finishRename(true)} />
          {:else}
            <button class="play" disabled={app.scanning || !label} onclick={() => play(f)}
              title={label ? `Play ${f.name}` : `This server has no "${f.effect}" effect`}>
              <b>{f.name}</b>
              <span>{label ?? `${f.effect} (not available)`}</span>
            </button>
            <button class="icon" title="Rename" aria-label="Rename {f.name}" onclick={() => startRename(f)}>
              <Pencil size={14} />
            </button>
            <button class="icon danger" title="Delete" aria-label="Delete {f.name}" onclick={() => favourites.remove(f.id)}>
              <Trash2 size={14} />
            </button>
          {/if}
        </li>
      {/each}
    </ul>
  {:else}
    <p class="muted">None yet. Run an effect, set it up how you like, then press ☆ in Now playing
      to keep it with its settings.</p>
  {/if}
  {#if favourites.error}<Alert tone="bad">{favourites.error}</Alert>{/if}
  <p class="muted where">{favourites.onServer
    ? "Kept on the server, so the phone's page and playlists have them too."
    : "Kept in this browser: the server doesn't keep favourites."}</p>
</Card>

<style>
  ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--s1); }
  li { display: flex; align-items: stretch; gap: 2px; border: 1px solid var(--border); border-radius: var(--r1);
    background: var(--surface); }
  li.on { border-color: var(--accent-border); background: var(--accent-bg); }
  li.on b { color: var(--accent); }
  .play { flex: 1; min-width: 0; text-align: left; display: flex; flex-direction: column; gap: 1px; cursor: pointer;
    padding: var(--s2) var(--s3); background: transparent; border: 0; color: var(--text); }
  .play b, .play span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .play span { font-size: var(--t-xs); color: var(--muted); }
  .play:disabled { opacity: 0.45; cursor: not-allowed; }
  .play:hover:not(:disabled) b { text-decoration: underline; }
  .icon { width: 30px; display: grid; place-items: center; background: transparent; border: 0; cursor: pointer;
    color: var(--muted); border-radius: var(--r1); }
  .icon:hover { color: var(--text); background: var(--surface-3); }
  .icon.danger:hover { color: var(--bad); }
  .name { flex: 1; margin: 4px; padding: 4px 8px; font: inherit; color: var(--text); background: var(--surface-2);
    border: 1px solid var(--accent-border); border-radius: var(--r1); }
  p { margin: 0; font-size: var(--t-sm); }
  .where { margin-top: var(--s2); font-size: var(--t-xs); }
</style>
