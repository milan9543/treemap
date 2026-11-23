<script lang="ts">
  // One device: its LEDs in 3D where the scan placed them, lit as they are now; a QR code
  // that opens the scan page on the phone for this device; its effects.
  import { ArrowLeft, Copy, Monitor, Pencil, ScanLine, Trash2 } from "@lucide/svelte";
  import { onDestroy, onMount } from "svelte";
  import Alert from "../components/ui/Alert.svelte";
  import Button from "../components/ui/Button.svelte";
  import Card from "../components/ui/Card.svelte";
  import { deviceApi, scanLink, type Device, type Info, type MapInfo } from "./api";
  import EffectsPanel from "./EffectsPanel.svelte";
  import LedView from "./LedView.svelte";
  import OrientationCard from "./OrientationCard.svelte";
  import Qr from "./Qr.svelte";
  import Status from "./Status.svelte";

  let { id, info }: { id: string; info: Info } = $props();

  const dev = $derived(deviceApi(id));
  let device = $state<Device | null>(null);
  let map = $state<MapInfo | null>(null);
  let missing = $state(false);
  let error = $state<string | null>(null);
  let copied = $state(false);
  let mapKey = "";

  const link = $derived(device ? scanLink(info, device) : "");
  const mismatch = $derived(device?.status.wled && device.led_count !== null
    && device.status.wled.led_count !== device.led_count ? device.status.wled.led_count : null);
  const date = (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";

  async function load() {
    try {
      device = await dev.get();
      error = null;
      const m = device.map;
      const key = m?.fits ? `${m.created}|${JSON.stringify(m.orientation)}|${JSON.stringify(m.counts)}` : "";
      if (key !== mapKey) {
        mapKey = key;
        map = key ? await dev.map() : null;
      }
    } catch (e) {
      if ((e as { status?: number }).status === 404) missing = true;
      else error = (e as Error).message;
    }
  }

  async function act(f: () => Promise<unknown>) {
    try {
      await f();
      error = null;
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  function rename() {
    const name = prompt("Name", device?.name)?.trim();
    if (name && name !== device?.name) void act(() => dev.update({ name }));
  }

  function remove() {
    if (!device || !confirm(`Take ${device.name} off the list? Its map and scans stay on the server's disk.`)) return;
    void dev.remove().then(() => (location.hash = "#/"), (e) => (error = (e as Error).message));
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch { /* no clipboard: the link is selectable */ }
  }

  let timer: ReturnType<typeof setInterval>;
  onMount(() => {
    void load();
    timer = setInterval(load, 2000);
  });
  onDestroy(() => clearInterval(timer));
</script>

{#if missing}
  <div class="gone"><p>There's no such device. <a href="#/">Back to the devices</a></p></div>
{:else if device}
  <div class="device-page">
    <section class="stage">
      <header class="head">
        <a class="back" href="#/" title="All devices"><ArrowLeft size={18} /></a>
        <div class="titles">
          <h1>{device.name}
            {#if device.virtual}<span class="tag"><Monitor size={11} /> virtual</span>{/if}
          </h1>
          <span class="mono muted">{device.host} · {device.led_count ?? "?"} LEDs</span>
        </div>
        <Status {device} long />
      </header>
      {#if map}
        <LedView {dev} {map} gamma={device.gamma ?? 1} />
        <div class="legend muted">
          {#if device.send === false}Preview: what the effect would show (the LEDs stay dark)
          {:else if device.effect || device.busy}What the LEDs show{:else}Nothing playing: pick an effect{/if}
          · drag to turn, scroll to zoom
        </div>
      {:else}
        <div class="empty">
          <ScanLine size={40} strokeWidth={1.4} />
          <p>{device.map && !device.map.fits ? `Its map is for ${device.map.led_count} LEDs: scan it again.`
            : "Not scanned yet."} Scan it with the phone to see its LEDs here, in 3D.</p>
        </div>
      {/if}
    </section>

    <aside class="side">
      {#if error}<Alert tone="bad">{error}</Alert>{/if}
      {#if device.error && device.send !== false}
        <Alert tone="warn">Can't send to the controller: {device.error}</Alert>
      {/if}
      {#each device.status.problems ?? [] as problem (problem)}
        <Alert tone="warn">{problem} <span class="muted small">(Checked every minute.)</span></Alert>
      {/each}
      {#if mismatch !== null}
        <Alert tone="warn">WLED now has {mismatch} LEDs; this device was set up with {device.led_count}.
          <Button size="sm" onclick={() => act(() => dev.update({ led_count: mismatch }))}>Use {mismatch} LEDs</Button>
          (the map must then be scanned again)</Alert>
      {/if}

      <Card title="Scan with the phone">
        {#if device.led_count === null}
          <p class="muted">Waiting for the controller to answer, to learn how many LEDs it has. Switch it on.</p>
        {:else}
          <div class="scan">
            <a href={link} target="_blank" rel="noreferrer" title="Open the scan page"><Qr text={link} size={148} /></a>
            <div class="scan-text">
              <p>Point the phone's camera at the code to open the scan page for <b>{device.name}</b>, in
                Chrome on an Android phone on the same Wi-Fi.</p>
              <button class="copy" onclick={copy}><Copy size={12} /> {copied ? "Copied" : "Copy the link"}</button>
            </div>
          </div>
          {#if info.url && /\/\/(127\.|localhost)/.test(info.url)}
            <p class="muted small">The link points at {info.url}, which the phone can't reach: run the
              server on the network (server.host 0.0.0.0).</p>
          {/if}
          {#if device.status.alive === false}
            <p class="muted small">The controller isn't answering: switch it on first, the scan lights its LEDs.</p>
          {/if}
          <p class="map-line">
            {#if device.map?.fits}
              Scanned {date(device.map.created)}: <span class="ok">{device.map.counts.ok}</span> found,
              <span class="warn">{device.map.counts.interpolated}</span> guessed,
              <span class="bad">{device.map.counts.failed}</span> missing.
            {:else}
              <span class="muted">Not scanned yet.</span>
            {/if}
          </p>
          {#if device.legacy_map}
            <div class="legacy">
              <span class="muted small">A map from before devices fits it ({device.led_count} LEDs).</span>
              <Button size="sm" onclick={() => act(() => dev.adoptMap())}>Use that map</Button>
            </div>
          {/if}
        {/if}
      </Card>

      {#if device.led_count !== null}
        {#key id}<EffectsPanel {dev} {device} onchange={load} />{/key}
      {/if}

      {#if device.map?.fits}
        {#key id}<OrientationCard {dev} shape={device.map.shape} orientation={device.map.orientation}
                                  scanning={device.busy === "scan"} onchange={load} />{/key}
      {/if}

      <Card title="Device">
        <dl>
          <dt>Address</dt><dd class="mono">{device.host}</dd>
          <dt>WLED</dt><dd>{device.status.wled ? `${device.status.wled.name || "WLED"} ${device.status.wled.version ?? ""}` : "not seen yet"}</dd>
          <dt>LEDs</dt><dd>{device.led_count ?? "not known yet"}</dd>
        </dl>
        <div class="row">
          <Button size="sm" icon={Pencil} onclick={rename}>Rename</Button>
          <Button size="sm" variant="danger" icon={Trash2} onclick={remove}>Remove</Button>
        </div>
      </Card>
    </aside>
  </div>
{:else if error}
  <div class="gone"><Alert tone="bad">{error}</Alert></div>
{/if}

<style>
  .device-page { display: grid; grid-template-columns: 1fr var(--sidebar-w); height: 100%; min-height: 0; }
  .stage { position: relative; min-height: 0; overflow: hidden; background: var(--bg); }
  .head { position: absolute; z-index: 1; top: 0; left: 0; right: 0; display: flex; align-items: center; gap: var(--s3);
    padding: var(--s3) var(--s4); background: linear-gradient(var(--bg), transparent); pointer-events: none; }
  .head > * { pointer-events: auto; }
  .back { display: grid; place-items: center; width: 30px; height: 30px; color: var(--text); border-radius: var(--r1); }
  .back:hover { background: var(--surface-3); }
  .titles { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  h1 { margin: 0; font-size: var(--t-xl); font-weight: 650; display: flex; align-items: center; gap: var(--s2); }
  .titles span { font-size: var(--t-sm); }
  .tag { display: inline-flex; align-items: center; gap: 3px; font-size: var(--t-xs); font-weight: 500; color: var(--info);
    border: 1px solid var(--info); border-radius: 999px; padding: 0 6px; }
  .legend { position: absolute; left: var(--s4); bottom: var(--s3); font-size: var(--t-xs); pointer-events: none; }
  .empty { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: var(--s3); color: var(--muted); text-align: center; padding: var(--s5); }
  .empty p { max-width: 360px; margin: 0; }
  .side { overflow-y: auto; padding: var(--s3); display: flex; flex-direction: column; gap: var(--s3);
    background: var(--surface); border-left: 1px solid var(--border); }
  p { margin: 0; font-size: var(--t-sm); }
  .small { font-size: var(--t-xs); }
  .scan { display: flex; gap: var(--s3); align-items: flex-start; }
  .scan-text { display: flex; flex-direction: column; gap: var(--s2); }
  .copy { align-self: flex-start; display: inline-flex; align-items: center; gap: 4px; background: none; border: 0; padding: 0;
    color: var(--accent); cursor: pointer; font-size: var(--t-sm); }
  .map-line { font-size: var(--t-sm); }
  .legacy { display: flex; align-items: center; justify-content: space-between; gap: var(--s2); }
  dl { display: grid; grid-template-columns: auto 1fr; gap: 3px var(--s3); margin: 0; font-size: var(--t-sm); }
  dt { color: var(--muted); }
  dd { margin: 0; overflow-wrap: anywhere; }
  .row { display: flex; gap: var(--s2); }
  .gone { padding: var(--s5); }
  @media (max-width: 860px) {
    .device-page { grid-template-columns: 1fr; grid-template-rows: 55vh auto; height: auto; }
    .side { border-left: 0; overflow: visible; }
  }
</style>
