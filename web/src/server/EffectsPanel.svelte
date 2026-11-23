<script lang="ts">
  // A device's effects: what's playing (polled, so a playlist moving on shows up), the
  // effect's controls built from GET /effects, brightness, and picking an effect,
  // favourite or playlist. Favourites and playlists are the server's, shared by every
  // device. Changes go out as you drag, one request at a time with the latest value.
  //
  // "Send to the LEDs" off keeps the frames on this page (the 3D view): a preview.
  import { ListMusic, Pencil, SkipForward, Square, Star, Sun, Trash2 } from "@lucide/svelte";
  import { onDestroy, onMount } from "svelte";
  import Alert from "../components/ui/Alert.svelte";
  import Button from "../components/ui/Button.svelte";
  import Card from "../components/ui/Card.svelte";
  import Segmented from "../components/ui/Segmented.svelte";
  import Toggle from "../components/ui/Toggle.svelte";
  import {
    api, type Device, type DeviceApi, type EffectInfo, type Favourite, type Params, type Playing,
    type Playlist, type PlaylistFields,
  } from "./api";
  import { coalesce } from "./coalesce";
  import EffectControls from "./EffectControls.svelte";
  import PlaylistEditor from "./PlaylistEditor.svelte";
  import Timing from "./Timing.svelte";

  let { dev, device, onchange }: { dev: DeviceApi; device: Device; onchange: () => void } = $props();

  type Tab = "favourites" | "effects" | "playlists";
  const POLL_MS = 1500;
  const GROUPS = [{ group: "3D", title: "3D" }, { group: "Classic", title: "Along the strip" }];

  let effects = $state<EffectInfo[]>([]);
  let favs = $state<Favourite[]>([]);
  let lists = $state<Playlist[]>([]);
  let playing = $state<Playing | null>(null);
  let local = $state<Params>({}); // set here, not yet confirmed by the server
  let brightness = $state<number | null>(null); // while dragging, 0-100
  let tab = $state<Tab>(loadTab());
  let error = $state<string | null>(null);
  let naming = $state<string | null>(null);
  let renaming = $state<{ id: string; name: string } | null>(null);
  let editing = $state<Playlist | "new" | null>(null);
  let nextAt = $state(0);
  let now = $state(Date.now());

  const hasMap = $derived(!!device.map?.fits);
  const running = $derived(effects.find((e) => e.name === playing?.effect) ?? null);
  const values = $derived<Params>({ ...(playing?.params ?? {}), ...local });
  const matching = $derived(playing?.effect
    ? favs.find((f) => f.effect === playing!.effect && sameParams(f.params, values)) : undefined);
  const started = $derived(favs.find((f) => f.id === playing?.favourite));
  const changedFrom = $derived(!matching && started && started.effect === playing?.effect ? started : null);
  const shownBrightness = $derived(brightness ?? Math.round((playing?.brightness ?? 1) * 100));
  const nextIn = $derived(Math.max(0, Math.round((nextAt - now) / 1000)));
  const tabs = $derived([
    { value: "favourites" as const, label: `Favourites${favs.length ? ` (${favs.length})` : ""}` },
    { value: "effects" as const, label: "Effects" },
    { value: "playlists" as const, label: `Playlists${lists.length ? ` (${lists.length})` : ""}` },
  ]);

  function loadTab(): Tab {
    try {
      return (localStorage.getItem("serverEffectsTab") as Tab) || "effects";
    } catch {
      return "effects";
    }
  }
  function setTab(t: Tab) {
    tab = t;
    try { localStorage.setItem("serverEffectsTab", t); } catch { /* not kept */ }
  }

  function sameParams(a: Params, b: Params): boolean {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    return [...keys].every((k) => JSON.stringify(a[k]) === JSON.stringify(b[k]));
  }

  /** "Plane · around": the effect plus the choices that differ from its defaults. */
  function defaultName(fx: EffectInfo, params: Params): string {
    const bits = fx.params.filter((p) => params[p.name] !== p.default && (p.kind === "choice" ||
      (p.kind === "bool" && params[p.name] === true)))
      .map((p) => (p.kind === "choice" ? String(params[p.name]) : p.label.toLowerCase()));
    return bits.length ? `${fx.label} · ${bits.join(", ")}` : fx.label;
  }

  const fail = (e: Error) => { error = e.message; };

  function show(p: Playing) {
    playing = p;
    nextAt = p.playlist ? Date.now() + p.playlist.next_s * 1000 : 0;
    if (p.error) error = p.error;
  }

  async function load() {
    try {
      const [e, f, l, p] = await Promise.all([api.effects(), api.favourites(), api.playlists(), dev.playing()]);
      effects = e.effects;
      favs = f.favourites;
      lists = l.playlists;
      show(p);
    } catch (e) {
      fail(e as Error);
    }
  }

  async function poll() {
    if (params.busy() || light.busy() || document.hidden) return;
    try {
      const p = await dev.playing();
      if (!params.busy()) show(p);
      if (p.favourite && !favs.some((f) => f.id === p.favourite)) favs = (await api.favourites()).favourites;
    } catch {
      /* the next poll tries again */
    }
  }

  async function run(start: () => Promise<Playing>) {
    try {
      local = {};
      show(await start());
      error = null;
      onchange();
    } catch (e) {
      fail(e as Error);
    }
  }

  const params = coalesce<Params>(async (change) => {
    const p = await dev.setParams(change);
    if (!params.busy()) {
      local = {};
      show(p);
    }
  }, fail, (a, b) => ({ ...a, ...b }));

  function setParam(name: string, value: unknown) {
    local = { ...local, [name]: value };
    void params.push({ [name]: value });
  }

  const light = coalesce<number>(async (v) => {
    const p = await dev.setBrightness(v);
    if (playing) playing.brightness = p.brightness;
  }, fail);

  async function setSend(on: boolean) {
    try {
      await dev.setSend(on);
      onchange();
    } catch (e) {
      fail(e as Error);
    }
  }

  // -- favourites -----------------------------------------------------------------------

  async function keep() {
    if (!running || naming === null) return;
    try {
      const f = await api.addFavourite({ name: naming.trim() || running.label, effect: running.name, params: values });
      favs = [...favs, f];
      naming = null;
      error = null;
    } catch (e) {
      fail(e as Error);
    }
  }

  async function updateFavourite(f: Favourite) {
    try {
      const updated = await api.updateFavourite(f.id, { params: values });
      favs = favs.map((x) => (x.id === f.id ? updated : x));
    } catch (e) {
      fail(e as Error);
    }
  }

  async function rename() {
    if (!renaming) return;
    const { id, name } = renaming;
    renaming = null;
    if (!name.trim() || name.trim() === favs.find((f) => f.id === id)?.name) return;
    try {
      const updated = await api.updateFavourite(id, { name: name.trim() });
      favs = favs.map((x) => (x.id === id ? updated : x));
    } catch (e) {
      fail(e as Error);
    }
  }

  async function removeFavourite(f: Favourite) {
    const used = lists.filter((l) => l.items.some((i) => i.favourite === f.id)).length;
    if (!confirm(`Delete the favourite "${f.name}"?` + (used ? ` It comes out of ${used} playlist${used === 1 ? "" : "s"} too.` : ""))) return;
    try {
      await api.deleteFavourite(f.id);
      favs = favs.filter((x) => x.id !== f.id);
      lists = (await api.playlists()).playlists;
    } catch (e) {
      fail(e as Error);
    }
  }

  // -- playlists ----------------------------------------------------------------------

  async function savePlaylist(fields: PlaylistFields) {
    try {
      const pl = editing === "new" || !editing ? await api.addPlaylist(fields) : await api.putPlaylist(editing.id, fields);
      lists = editing === "new" ? [...lists, pl] : lists.map((l) => (l.id === pl.id ? pl : l));
      editing = null;
      error = null;
    } catch (e) {
      fail(e as Error);
    }
  }

  async function deletePlaylist() {
    if (!editing || editing === "new") return;
    const id = editing.id;
    try {
      await api.deletePlaylist(id);
      lists = lists.filter((l) => l.id !== id);
      editing = null;
    } catch (e) {
      fail(e as Error);
    }
  }

  const minutes = (pl: Playlist) => Math.round(pl.items.reduce((s, i) => s + i.duration_s, 0) / 6) / 10;
  const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const focus = (el: HTMLInputElement) => { el.focus(); el.select(); };

  let timer: ReturnType<typeof setInterval> | undefined;
  let ticker: ReturnType<typeof setInterval> | undefined;
  onMount(() => {
    void load();
    timer = setInterval(poll, POLL_MS);
    ticker = setInterval(() => (now = Date.now()), 1000);
  });
  onDestroy(() => {
    clearInterval(timer);
    clearInterval(ticker);
  });
</script>

<Card title="Now playing">
  {#snippet actions()}
    {#if running}
      {#if matching}
        <span class="star on" title="A favourite: {matching.name}"><Star size={15} fill="currentColor" /></span>
      {:else}
        <button class="star" title="Keep as a favourite, with these settings"
                onclick={() => (naming = defaultName(running, values))}><Star size={15} /></button>
      {/if}
      <Button size="sm" variant="danger" icon={Square} onclick={() => run(() => dev.stop())}>Stop</Button>
    {/if}
  {/snippet}
  {#if running}
    <div class="now">
      <b>{matching?.name ?? running.label}</b>
      {#if playing?.playlist}
        <span class="muted">
          <ListMusic size={12} /> {playing.playlist.name} · next in <span class="mono">{clock(nextIn)}</span>
          <button class="link" onclick={() => run(() => dev.playNext())}><SkipForward size={12} /> Next</button>
        </span>
      {:else}
        <span class="muted">{matching ? `${running.label}: ` : ""}{running.description}</span>
      {/if}
    </div>
    {#if naming !== null}
      <form class="row" onsubmit={(e) => { e.preventDefault(); void keep(); }}>
        <input type="text" maxlength="80" aria-label="Favourite name" bind:value={naming} use:focus />
        <Button size="sm" variant="primary" onclick={keep}>Keep</Button>
        <Button size="sm" onclick={() => (naming = null)}>Cancel</Button>
      </form>
    {/if}
    {#if changedFrom}
      <div class="changed">
        <span>Changed from <b>{changedFrom.name}</b></span>
        <Button size="sm" onclick={() => updateFavourite(changedFrom)}>Update it</Button>
      </div>
    {/if}
    {#if running.params.length}<EffectControls fx={running} {values} onchange={setParam} />{/if}
  {:else if device.busy === "scan"}
    <p class="muted">A scan is using the LEDs. Effects can play once it's over.</p>
  {:else}
    <p class="muted">Nothing. Pick an effect below.</p>
  {/if}
  <label class="bright">
    <Sun size={15} />
    <input type="range" min="0" max="100" step="1" value={shownBrightness} aria-label="Brightness"
           oninput={(e) => { brightness = Number(e.currentTarget.value); void light.push(brightness / 100); }}
           onchange={() => setTimeout(() => (brightness = null), 600)} />
    <output class="mono">{shownBrightness}%</output>
  </label>
  <div class="send">
    <Toggle checked={device.send ?? true} onchange={setSend}
            title="Off: effects play on this page only, the LEDs stay dark">Send to the LEDs</Toggle>
    {#if device.send === false}
      <span class="muted">Preview: on this page only</span>
    {:else if device.status.alive === false}
      <span class="muted">The controller isn't answering: shown here only</span>
    {/if}
  </div>
  {#if running && device.timing}<Timing t={device.timing} sending={device.send !== false} />{/if}
  {#if error}<Alert tone="bad">{error}</Alert>{/if}
</Card>

{#if editing}
  <Card title={editing === "new" ? "A new playlist" : "Edit the playlist"}>
    {#key editing}
      <PlaylistEditor playlist={editing === "new" ? null : editing} favourites={favs}
                      onsave={savePlaylist} ondelete={editing === "new" ? undefined : deletePlaylist}
                      oncancel={() => (editing = null)} />
    {/key}
  </Card>
{:else}
  <div class="tabs"><Segmented value={tab} onchange={setTab} options={tabs} /></div>

  {#if tab === "favourites"}
    <Card>
      {#if favs.length}
        <ul class="list">
          {#each favs as f (f.id)}
            {@const fx = effects.find((e) => e.name === f.effect)}
            <li class:on={playing?.favourite === f.id && playing?.effect === f.effect}>
              {#if renaming?.id === f.id}
                <form onsubmit={(e) => { e.preventDefault(); void rename(); }}>
                  <input type="text" maxlength="80" aria-label="Name" bind:value={renaming.name} use:focus onblur={rename} />
                </form>
              {:else}
                <button class="play" disabled={!fx || (fx.needs_map && !hasMap)} onclick={() => run(() => dev.playFavourite(f.id))}>
                  <b>{f.name}</b>
                  <span>{fx ? fx.label + (fx.needs_map && !hasMap ? " · needs the map" : "") : `${f.effect}: not on this server`}</span>
                </button>
                <button class="icon" title="Rename" onclick={() => (renaming = { id: f.id, name: f.name })}><Pencil size={13} /></button>
                <button class="icon bad" title="Delete" onclick={() => removeFavourite(f)}><Trash2 size={13} /></button>
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">None yet. Play an effect, set it up how you like, then press ☆ to keep it.
          Favourites are shared by every device.</p>
      {/if}
    </Card>
  {:else if tab === "effects"}
    {#each GROUPS as g (g.group)}
      {@const fxs = effects.filter((e) => e.group === g.group)}
      {#if fxs.length}
        <Card title={g.title}>
          {#if g.group === "3D" && !hasMap}<p class="muted">These need the map: scan the device first.</p>{/if}
          <div class="grid">
            {#each fxs as e (e.name)}
              <button class="fx" class:on={playing?.effect === e.name} title={e.description}
                      disabled={(e.needs_map && !hasMap) || device.busy === "scan"} onclick={() => run(() => dev.play(e.name))}>
                <b>{e.label}</b>
                <span>{e.description}</span>
              </button>
            {/each}
          </div>
        </Card>
      {/if}
    {/each}
  {:else}
    <Card>
      {#snippet actions()}
        <Button size="sm" disabled={!favs.length} onclick={() => (editing = "new")}>New playlist</Button>
      {/snippet}
      {#if lists.length}
        <ul class="list">
          {#each lists as pl (pl.id)}
            <li class:on={playing?.playlist?.id === pl.id}>
              <button class="play" disabled={!pl.items.length} onclick={() => run(() => dev.playPlaylist(pl.id))}>
                <b>{pl.name}</b>
                <span>{pl.items.length
                  ? `${pl.items.length} favourite${pl.items.length === 1 ? "" : "s"}, ${minutes(pl)} min${pl.shuffle ? ", shuffled" : ""}`
                  : "empty"}</span>
              </button>
              <button class="icon" title="Edit" onclick={() => (editing = pl)}><Pencil size={13} /></button>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">A playlist plays favourites in turn, each for its own time, with a crossfade
          between them, round and round.{favs.length ? "" : " Keep some favourites first."}</p>
      {/if}
    </Card>
  {/if}
{/if}

<style>
  p { margin: 0; font-size: var(--t-sm); }
  .now { display: flex; flex-direction: column; gap: 2px; font-size: var(--t-sm); }
  .now b { font-size: var(--t-lg); }
  .now span { display: inline-flex; align-items: center; gap: 4px; flex-wrap: wrap; }
  .link { display: inline-flex; align-items: center; gap: 3px; background: none; border: 0; padding: 0 0 0 6px;
    color: var(--accent); cursor: pointer; font-size: var(--t-sm); }
  .star { display: grid; place-items: center; width: 28px; height: 26px; color: var(--muted); background: transparent;
    border: 1px solid var(--border); border-radius: var(--r1); cursor: pointer; }
  .star:hover { color: var(--text); border-color: var(--border-strong); }
  .star.on { color: var(--warn); border-color: var(--warn); cursor: default; }
  .row { display: flex; gap: var(--s2); align-items: center; }
  .changed { display: flex; align-items: center; justify-content: space-between; gap: var(--s2);
    font-size: var(--t-sm); color: var(--muted); }
  .changed b { color: var(--text); font-weight: 600; }
  .bright { display: grid; grid-template-columns: 20px 1fr 44px; align-items: center; gap: var(--s2); color: var(--muted); }
  .bright output { text-align: right; font-size: var(--t-xs); color: var(--text); }
  .send { display: flex; align-items: center; justify-content: space-between; gap: var(--s2); font-size: var(--t-sm); }
  .send span { font-size: var(--t-xs); }
  .tabs :global(.seg) { display: flex; }
  .tabs :global(.seg button) { flex: 1; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s2); }
  .fx { text-align: left; display: flex; flex-direction: column; gap: 2px; padding: var(--s2) var(--s3); cursor: pointer;
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--r1); color: var(--text); }
  .fx span { font-size: var(--t-xs); color: var(--muted); display: -webkit-box; -webkit-line-clamp: 2;
    line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .fx:hover:not(:disabled) { border-color: var(--border-strong); background: var(--surface-3); }
  .fx.on { border-color: var(--accent-border); background: var(--accent-bg); }
  .fx.on b { color: var(--accent); }
  .fx:disabled { opacity: 0.45; cursor: not-allowed; }
  .list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--s1); }
  .list li { display: flex; align-items: stretch; gap: 2px; border: 1px solid var(--border); border-radius: var(--r1);
    background: var(--surface); }
  .list li.on { border-color: var(--accent-border); background: var(--accent-bg); }
  .list li.on b { color: var(--accent); }
  .list form { flex: 1; padding: 4px; }
  .play { flex: 1; min-width: 0; text-align: left; display: flex; flex-direction: column; gap: 1px; cursor: pointer;
    padding: var(--s2) var(--s3); background: transparent; border: 0; color: var(--text); }
  .play b, .play span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .play span { font-size: var(--t-xs); color: var(--muted); }
  .play:disabled { opacity: 0.45; cursor: not-allowed; }
  .icon { width: 30px; display: grid; place-items: center; background: transparent; border: 0; cursor: pointer;
    color: var(--muted); border-radius: var(--r1); }
  .icon:hover { color: var(--text); background: var(--surface-3); }
  .icon.bad:hover { color: var(--bad); }
</style>
