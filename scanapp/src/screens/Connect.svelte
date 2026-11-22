<script lang="ts">
  import { onMount } from "svelte";
  import { Api, ApiError, API_VERSION, normaliseServer, type Info, type Shape } from "../lib/api";
  import { app, browserProblem, disconnect, useServer } from "../lib/state.svelte";

  let address = $state(app.server.replace(/^http:\/\//, ""));
  let connecting = $state(false);
  let problem = $state<{ kind: "unreachable" | "origin" | "version" | "other"; text: string } | null>(null);
  const browser = browserProblem();

  async function connect() {
    const server = normaliseServer(address);
    if (!server) return;
    connecting = true;
    problem = null;
    const api = new Api(server);
    try {
      const info: Info = await api.info();
      if (info.api !== API_VERSION) {
        problem = { kind: "version", text: `The server speaks version ${info.api} of the API and ` +
          `this page version ${API_VERSION}. Update ${info.api < API_VERSION ? "the server" : "this page (reload it)"}.` };
        return;
      }
      if (app.info?.led_count === undefined) app.shape = info.shape;
      useServer(api, info);
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
    <p class="muted">Map where every LED is, by filming them with this phone.</p>
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
        starts. Chrome asks to let this page reach devices on your network: allow it.</p>
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
          <span>{info.server} <span class="ok-dot" aria-hidden="true"></span></span>
          <button type="button" class="small-btn" onclick={() => { problem = null; disconnect(); }}>
            Disconnect</button>
        </dd>
        <dt>LEDs</dt>
        <dd class="num">{info.led_count}
          {#if info.controllers.length}
            on {info.controllers.length === 1 ? info.controllers[0].host
              : `${info.controllers.length} controllers`}
          {:else if info.output === "sim"}(simulated){/if}
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
    {/if}
  </section>

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
</style>
