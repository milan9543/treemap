<script lang="ts">
  // Step 0: reach the server, and the device to scan on it. The server's QR code opens
  // this page with both; without a device, pick one from the server's list.
  import { onMount } from "svelte";
  import {
    Api, ApiError, API_VERSION, normaliseServer, serverApi, type DeviceSummary, type Shape,
  } from "../lib/api";
  import { app, browserProblem, disconnect, useServer } from "../lib/state.svelte";

  let address = $state(app.server.replace(/^http:\/\//, ""));
  let connecting = $state(false);
  let serverName = $state<string | null>(null);
  let devices = $state<DeviceSummary[] | null>(null); // to pick from, when none is chosen
  let problem = $state<{ kind: "unreachable" | "origin" | "version" | "other"; text: string } | null>(null);
  const browser = browserProblem();

  async function connect(device = app.device) {
    const server = normaliseServer(address);
    if (!server) return;
    connecting = true;
    problem = null;
    try {
      const srv = serverApi(server);
      const about = await srv.info();
      if (about.api !== API_VERSION) {
        problem = { kind: "version", text: `The server speaks version ${about.api} of the API and ` +
          `this page version ${API_VERSION}. Update ${about.api < API_VERSION ? "the server" : "this page (reload it)"}.` };
        return;
      }
      serverName = about.server;
      if (device) {
        try {
          const api = new Api(server, device);
          const info = await api.info();
          if (info.led_count === null) {
            problem = { kind: "other", text: `${info.name} hasn't answered the server yet, so its LED ` +
              "count isn't known. Switch it on and try again." };
            return;
          }
          if (app.info?.id !== info.id) app.shape = info.map?.shape ?? info.shape;
          useServer(api, info);
          devices = null;
          return;
        } catch (e) {
          if ((e as ApiError).status !== 404) throw e;
          app.device = ""; // gone from the server: pick another
        }
      }
      devices = (await srv.devices()).devices;
    } catch (e) {
      const err = e as ApiError;
      problem = err.status === 0 ? { kind: "unreachable", text: err.message }
        : err.status === 403 ? { kind: "origin", text: err.message }
        : { kind: "other", text: err.message };
    } finally {
      connecting = false;
    }
  }

  function pick(shape: Shape) {
    app.shape = shape;
  }

  function otherDevice() {
    app.api = null;
    app.info = null;
    void connect("");
  }

  const date = (iso: string | null) =>
    iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";

  onMount(() => {
    if (address && !app.info) void connect();
  });

  const info = $derived(app.info);
</script>

<main class="page">
  <header class="head">
    <h1>treemap</h1>
    <p class="muted">Map where every LED is, by filming them with this phone. Open this page
      from the QR code on the server's page.</p>
  </header>

  {#if browser}
    <div class="note warn">{browser}</div>
  {/if}

  <section class="card">
    <h2>Server</h2>
    <form class="row" onsubmit={(e) => { e.preventDefault(); void connect(); }}>
      <input class="grow" type="text" inputmode="url" autocomplete="off" autocapitalize="off"
             spellcheck="false" placeholder="192.168.1.20:8765" aria-label="Server address"
             bind:value={address} />
      <button type="submit" class={info ? "" : "primary"} disabled={connecting || !address.trim()}>
        {connecting ? "Connecting…" : info ? "Reconnect" : "Connect"}
      </button>
    </form>
    {#if !info && !problem}
      <p class="small muted hint">The address <span class="mono">treemap serve</span> prints when it
        starts (the server's QR code fills it in). Chrome asks to let this page reach devices on
        your network: allow it.</p>
    {/if}

    {#if problem?.kind === "unreachable"}
      <div class="note bad">
        {problem.text}
        <ul>
          <li>Is <span class="mono">treemap serve</span> running, and is the address right?</li>
          <li>Is this phone on the same Wi-Fi as the server?</li>
          <li>Did Chrome ask about devices on your local network? If you blocked it, tap the
            icon left of the address bar, then <em>Permissions</em>, and allow
            <em>Local network access</em>.</li>
        </ul>
      </div>
    {:else if problem?.kind === "origin"}
      <div class="note bad">The server doesn't let this page in. Add
        <span class="mono">{location.origin}</span> to <span class="mono">server.origins</span> in
        its config and restart it.</div>
    {:else if problem}
      <div class="note bad">{problem.text}</div>
    {/if}

    {#if info}
      <dl class="facts connected">
        <dt>Server</dt>
        <dd class="server">
          <span>{serverName ?? app.server} <span class="ok-dot" aria-hidden="true"></span></span>
          <button type="button" class="small-btn" onclick={() => { problem = null; disconnect(); }}>
            Disconnect</button>
        </dd>
        <dt>Device</dt>
        <dd class="server">
          <span><strong>{info.name}</strong> <span class="muted">{info.virtual ? "virtual, " : ""}{info.led_count} LEDs</span></span>
          <button type="button" class="small-btn" onclick={otherDevice}>Other</button>
        </dd>
        <dt>Map</dt>
        <dd>
          {#if !info.map}
            none yet
          {:else if !info.map.fits}
            for {info.map.led_count} LEDs: scan again
          {:else}
            <span class="num">{info.map.counts.ok}</span> found,
            <span class="num">{info.map.counts.interpolated}</span> guessed,
            <span class="num">{info.map.counts.failed}</span> missing
            <span class="muted">({info.map.shape}, {date(info.map.created)})</span>
          {/if}
        </dd>
      </dl>
      {#if info.status.alive === false}
        <div class="note warn">The server can't reach this controller ({info.status.error ?? "no answer"}).
          Switch it on: the scan lights its LEDs.</div>
      {/if}
    {/if}
  </section>

  {#if devices && !info}
    <section class="card">
      <h2>Which device?</h2>
      {#if devices.length}
        <div class="stack">
          {#each devices as d (d.id)}
            <button class="device" disabled={d.led_count === null || connecting} onclick={() => connect(d.id)}>
              <strong>{d.name}</strong>
              <span class="small muted">{d.host} · {d.led_count === null ? "not answering yet" : `${d.led_count} LEDs`}{d.virtual ? " · virtual" : ""}</span>
            </button>
          {/each}
        </div>
      {:else}
        <p class="small muted">The server has no devices yet. Add your WLED controller on the server's
          page first, then scan its QR code.</p>
      {/if}
    </section>
  {/if}

  {#if info}
    {#if info.busy === "scan"}
      <section class="card">
        <h2>A scan is running</h2>
        <p class="muted small">Pick it up here: the page films for it again. Disconnecting
          leaves it waiting on the server; stop it from its screen first.</p>
        <button class="primary wide" onclick={() => (app.screen = "scan")}>Go to the scan</button>
      </section>
    {:else}
      <section class="card">
        <h2>What are you scanning?</h2>
        <div class="segmented" role="group" aria-label="Shape">
          <button aria-pressed={app.shape === "tree"} onclick={() => pick("tree")}>
            <strong>A tree</strong><span>LEDs wound round it; you walk round it.</span>
          </button>
          <button aria-pressed={app.shape === "flat"} onclick={() => pick("flat")}>
            <strong>Flat</strong><span>LEDs on the floor or a wall, filmed from one side.</span>
          </button>
        </div>
        {#if info.map?.fits}
          <p class="small muted replace">A new scan replaces the current map.</p>
        {/if}
        <div class="actions">
          <button onclick={() => (app.screen = "scan")}>Skip to the scan</button>
          <button class="primary" onclick={() => (app.screen = "wiring")}>Check the wiring</button>
        </div>
      </section>
      {#if info.map?.fits}
        <section class="card">
          <h2>The current map</h2>
          <p class="small muted">Fix missing LEDs, or set which way it faces, without scanning again.</p>
          <button class="wide" onclick={() => { app.shape = info.map!.shape; app.screen = "review"; }}>
            Review the map</button>
        </section>
      {/if}
    {/if}
  {/if}
</main>

<style>
  .head { margin: 8px 0 16px; }
  .head p { margin: 0; }
  .hint { margin: 10px 0 0; }
  .connected { margin-top: 14px; }
  .ok-dot {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: var(--ok); margin-left: 4px; vertical-align: 1px;
  }
  .replace { margin: 10px 0 0; }
  .server { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .small-btn { min-height: 32px; padding: 4px 12px; font-size: 13px; }
  .wide { width: 100%; }
  .device { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; text-align: left; font-weight: 500; }
</style>
