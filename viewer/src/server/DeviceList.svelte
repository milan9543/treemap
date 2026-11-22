<script lang="ts">
  // The devices the server drives, and adding one by its address.
  import { Monitor, Plus } from "@lucide/svelte";
  import { onDestroy, onMount } from "svelte";
  import Alert from "../components/ui/Alert.svelte";
  import Card from "../components/ui/Card.svelte";
  import { api, type Device } from "./api";
  import Status from "./Status.svelte";

  let devices = $state<Device[] | null>(null);
  let host = $state("");
  let name = $state("");
  let adding = $state(false);
  let error = $state<string | null>(null);

  async function load() {
    try {
      devices = (await api.devices()).devices;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function add(e: SubmitEvent) {
    e.preventDefault();
    if (!host.trim()) return;
    adding = true;
    error = null;
    try {
      const d = await api.addDevice({ host: host.trim(), ...(name.trim() ? { name: name.trim() } : {}) });
      host = name = "";
      location.hash = `#/device/${d.id}`;
    } catch (err) {
      error = (err as Error).message;
    } finally {
      adding = false;
    }
  }

  const mapText = (d: Device) => {
    if (d.led_count === null) return "LED count not known yet";
    if (!d.map) return "not scanned yet";
    if (!d.map.fits) return `map for ${d.map.led_count} LEDs: scan again`;
    const c = d.map.counts;
    return `scanned: ${c.ok} found${c.interpolated ? `, ${c.interpolated} guessed` : ""}${c.failed ? `, ${c.failed} missing` : ""}`;
  };

  let timer: ReturnType<typeof setInterval>;
  onMount(() => {
    void load();
    timer = setInterval(load, 3000);
  });
  onDestroy(() => clearInterval(timer));
</script>

<div class="list-page">
  <h1>Devices</h1>
  {#if devices === null}
    <p class="muted">Loading…</p>
  {:else if devices.length}
    <div class="grid">
      {#each devices as d (d.id)}
        <a class="device" href="#/device/{d.id}">
          <div class="top">
            <b>{d.name}</b>
            {#if d.virtual}<span class="tag" title="treemap sim wled"><Monitor size={11} /> virtual</span>{/if}
            <span class="grow"></span>
            <Status device={d} />
          </div>
          <span class="mono muted">{d.host}</span>
          <span>{d.led_count ?? "?"} LEDs · {mapText(d)}</span>
          <span class="muted">{d.busy === "scan" ? "scanning" : d.effect ? `playing ${d.effect}${d.send === false ? " (preview)" : ""}` : " "}</span>
        </a>
      {/each}
    </div>
  {:else}
    <p class="empty muted">No devices yet. Add your WLED controller by its address below. Each
      device gets its own scan, map and effects.</p>
  {/if}

  <Card title="Add a controller">
    <form class="add" onsubmit={add}>
      <label>
        <span>Address</span>
        <input type="text" placeholder="192.168.1.50 or wled-tree.local" bind:value={host}
               autocomplete="off" spellcheck="false" />
      </label>
      <label>
        <span>Name <i class="muted">(optional)</i></span>
        <input type="text" placeholder="its WLED name" maxlength="60" bind:value={name} />
      </label>
      <button class="submit" type="submit" disabled={adding || !host.trim()}>
        <Plus size={15} /> {adding ? "Asking it…" : "Add"}
      </button>
    </form>
    <p class="muted hint">Its LED count is read from WLED (set it in WLED's LED Preferences). A
      controller that's off can be added too: the server picks it up when it answers. For a virtual
      one on a screen, run <code>treemap sim wled</code> and add the address it prints, like
      <code>127.0.0.1:8780</code>.</p>
    {#if error}<Alert tone="bad">{error}</Alert>{/if}
  </Card>
</div>

<style>
  .list-page { max-width: 980px; margin: 0 auto; padding: var(--s5) var(--s4); display: flex; flex-direction: column;
    gap: var(--s4); }
  h1 { margin: 0; font-size: var(--t-xl); font-weight: 650; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: var(--s3); }
  .device { display: flex; flex-direction: column; gap: 3px; padding: var(--s3) var(--s4); text-decoration: none;
    color: var(--text); background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r2);
    font-size: var(--t-sm); }
  .device:hover { border-color: var(--border-strong); background: var(--surface-3); }
  .top { display: flex; align-items: center; gap: var(--s2); }
  .top b { font-size: var(--t-lg); }
  .grow { flex: 1; }
  .tag { display: inline-flex; align-items: center; gap: 3px; font-size: var(--t-xs); color: var(--info);
    border: 1px solid var(--info); border-radius: 999px; padding: 0 6px; }
  .empty { margin: 0; }
  .add { display: grid; grid-template-columns: 2fr 1.4fr auto; gap: var(--s2); align-items: end; }
  .add label { display: flex; flex-direction: column; gap: 3px; font-size: var(--t-sm); color: var(--muted); }
  .add input { padding: 7px 10px; font-size: var(--t-md); }
  .submit { display: inline-flex; align-items: center; gap: 5px; height: 34px; padding: 0 var(--s4); cursor: pointer;
    background: var(--accent); color: #062016; font-weight: 600; border: 0; border-radius: var(--r1); }
  .submit:disabled { opacity: 0.45; cursor: default; }
  .hint { margin: 0; font-size: var(--t-sm); }
  @media (max-width: 640px) { .add { grid-template-columns: 1fr; } }
</style>
