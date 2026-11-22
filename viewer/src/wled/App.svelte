<script lang="ts">
  // The virtual WLED's page: the layout full screen, lit by what arrives over DDP, and a
  // panel (hidden while walking, so the phone films only the LEDs) for the status, the
  // config line for `treemap serve`, the view (rotate, optionally turning by itself, or
  // walk; see controls.ts), test lights, and new layouts.
  //
  // Test lights light the layout from this page, to look at it without the server. DDP
  // wins whenever it lights anything (see `testing`).
  import { onMount } from "svelte";
  import { applyFrame, camera, renderer, resize, scene, show } from "./scene";
  import type { Layout, Status } from "./types";
  import { autoRotate, goHome, look, setMode, update, walkKey, type Mode } from "./controls";
  import type { Home } from "./scene";

  let host = $state<HTMLDivElement>();
  let status = $state<Status | null>(null);
  let connected = $state(false);
  let locked = $state(false);
  let panel = $state(true);
  let layout = $state<Layout | null>(null);
  let home: Home | null = null;
  let copied = $state(false);
  const STILL_FPS = 3; // below this, DDP is holding a still frame, not playing

  // the view, remembered
  function remembered<T>(key: string, fallback: T): T {
    try {
      const v = localStorage.getItem(`wled.${key}`);
      return v === null ? fallback : (JSON.parse(v) as T);
    } catch {
      return fallback;
    }
  }
  function remember(key: string, v: unknown) {
    try {
      localStorage.setItem(`wled.${key}`, JSON.stringify(v));
    } catch {
      /* not remembered */
    }
  }
  let mode = $state<Mode>(remembered("mode", "rotate"));
  let turning = $state<boolean>(remembered("turning", false));
  let turnS = $state<number>(remembered("turnS", 40)); // seconds per turn
  $effect(() => {
    remember("mode", mode);
    remember("turning", turning);
    remember("turnS", turnS);
  });
  // A flat layout would only turn edge-on: it doesn't turn by itself.
  $effect(() => autoRotate(mode === "rotate" && turning && layout?.shape === "tree" ? turnS : 0));

  // What's lighting the LEDs, for the badge (fixed width) and the line under it.
  const link = $derived.by(() => {
    if (!connected) return { kind: "off", text: "Offline", title: "Reconnecting to treemap sim wled…" };
    if (!status?.live) return { kind: "idle", text: "Idle", title: "Waiting for treemap serve" };
    const from = `from ${status.source ?? "?"}`;
    // the server re-sends a still frame about once a second to hold WLED in realtime mode
    if (status.fps < STILL_FPS && ddpDark) return { kind: "idle", text: "Idle", title: `treemap serve at ${status.source ?? "?"} shows nothing` };
    if (status.fps < STILL_FPS) return { kind: "still", text: "Still frame", title: `Holding a still frame ${from}` };
    return { kind: "live", text: `${Math.round(status.fps)} fps`, title: `Live ${from}` };
  });
  const KEYS: [string, string][] = [["M", "rotate / walk"], ["Space", "turn"], ["R", "reset"],
                                     ["L", "lights"], ["H", "hide"]];

  function switchMode(m: Mode) {
    mode = m;
    setMode(m, home);
  }
  type Lights = "off" | "white" | "colours";
  const LIGHTS: Lights[] = ["off", "white", "colours"];
  let lights = $state<Lights>("off");

  // the new-layout form
  let shape = $state<"tree" | "flat">("tree");
  let leds = $state(400);
  let strips = $state(2);
  let pattern = $state<"auto" | "rows" | "spiral">("auto");
  let seed = $state("");
  let busy = $state(false);
  let error = $state<string | null>(null);
  let countChanged = $state(false);
  let layoutOpen = $state(false); // the New layout section

  let ws: WebSocket | null = null;
  let nextId = 1;

  /** Every LED white, or in the scan code's colours in turn (red, green, blue, white). */
  function testFrame(n: number, mode: Lights): ArrayBuffer {
    const f = new Uint8Array(n * 3);
    const rgb = [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]];
    for (let i = 0; i < n; i++) f.set(mode === "white" ? rgb[3] : mode === "colours" ? rgb[i % 4] : [0, 0, 0], i * 3);
    return f.buffer;
  }

  // What DDP last sent, and whether it was all dark.
  let ddp: ArrayBuffer | null = null;
  let ddpDark = $state(true);
  // Test lights show unless DDP is lighting something: nothing arriving, or only the dark
  // still frame `treemap serve` re-sends (about once a second) to hold realtime mode.
  const testing = $derived(lights !== "off" &&
    (!status?.live || (status.fps < STILL_FPS && ddpDark)));
  $effect(() => {
    if (!layout) return;
    if (testing) applyFrame(testFrame(layout.led_count, lights));
    else if (ddp) applyFrame(ddp);
  });
  async function loadLayout() {
    const r = await fetch("/api/layout", { cache: "no-store" });
    if (!r.ok) return;
    const l = (await r.json()) as Layout;
    layout = l;
    shape = l.shape;
    leds = l.led_count;
    strips = l.strands.length;
    if (l.shape === "flat") pattern = (l as { spec?: { pattern?: typeof pattern } }).spec?.pattern ?? "auto";
    home = show(l);
    setMode(mode, home);
  }

  function connect() {
    ws = new WebSocket(`ws://${location.host}/ws`);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      connected = true;
      void loadLayout();
    };
    ws.onclose = () => {
      connected = false;
      setTimeout(connect, 1000);
    };
    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        ddp = ev.data;
        ddpDark = new Uint8Array(ev.data).every((v) => v === 0);
        if (!testing) applyFrame(ev.data);
        return;
      }
      const m = JSON.parse(ev.data);
      if (m.type === "status") status = m;
      else if (m.type === "layout") void loadLayout();
      else if (m.type === "generated") {
        busy = false;
        error = m.ok ? null : m.error;
        if (error) layoutOpen = true;
      }
    };
  }

  function generate() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const per = Array.from({ length: strips }, (_, i) =>
      Math.floor(leds / strips) + (i < leds % strips ? 1 : 0));
    const spec: Record<string, unknown> = { strips: per.map((n) => ({ leds: n })) };
    if (seed.trim()) spec.seed = Number(seed);
    if (shape === "flat") spec.pattern = pattern;
    countChanged = leds !== layout?.led_count;
    busy = true;
    error = null;
    ws.send(JSON.stringify({ type: "generate", id: nextId++, shape, spec }));
  }

  async function copy() {
    if (!status) return;
    try {
      await navigator.clipboard.writeText(status.controller);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      /* not allowed: it's on screen to copy by hand */
    }
  }

  function onKey(e: KeyboardEvent, down: boolean) {
    if (walkKey(e, down)) return;
    const t = e.target as HTMLElement | null;
    if (!down || (t && (t.tagName === "INPUT" || t.tagName === "SELECT"))) return;
    if (e.code === "KeyH") panel = !panel;
    else if (e.code === "KeyM") switchMode(mode === "rotate" ? "walk" : "rotate");
    else if (e.code === "Space" && mode === "rotate" && t?.tagName !== "BUTTON") {
      turning = !turning;
      e.preventDefault();
    }
    else if (e.code === "KeyL") lights = LIGHTS[(LIGHTS.indexOf(lights) + 1) % LIGHTS.length];
    else if (e.code === "KeyR" && home) goHome(home);
  }

  onMount(() => {
    host!.appendChild(renderer.domElement);
    const fit = () => resize(host!.clientWidth, host!.clientHeight);
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(host!);
    look.addEventListener("lock", () => (locked = true));
    look.addEventListener("unlock", () => (locked = false));
    let raf = 0;
    const loop = () => {
      update();
      renderer.render(scene, camera);
      raf = requestAnimationFrame(loop);
    };
    loop();
    connect();
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      ws?.close();
    };
  });
</script>

<svelte:window onkeydown={(e) => onKey(e, true)} onkeyup={(e) => onKey(e, false)} />

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="view" class:walk={mode === "walk"} bind:this={host}
     onclick={() => mode === "walk" && look.lock()}></div>

{#if panel && !locked}
  <aside class="panel">
    <header>
      <div class="title">
        <h1>Virtual WLED</h1>
        <div class="sub num">
          {#if status}{status.led_count} LEDs · {status.shape === "flat" ? "flat" : "tree"}{:else}&nbsp;{/if}
        </div>
      </div>
      <span class="badge {link.kind}" title={link.title}><i></i><span class="num">{link.text}</span></span>
    </header>
    <div class="source" title={link.title}>{link.title}</div>

    <section>
      <div class="head">
        <h2>View</h2>
        <div class="seg" role="group" aria-label="View">
          <button aria-pressed={mode === "rotate"} onclick={() => switchMode("rotate")}>Rotate</button>
          <button aria-pressed={mode === "walk"} onclick={() => switchMode("walk")}>Walk</button>
        </div>
      </div>
      {#if mode === "rotate"}
        {#if layout?.shape !== "flat"}
          <div class="turn" class:on={turning}>
            <label class="switch">
              <input type="checkbox" role="switch" bind:checked={turning} />
              <span class="track"><span class="knob"></span></span>
              Turn by itself
            </label>
            <span class="num value">{turnS} s / turn</span>
          </div>
          <input class="range" type="range" min="10" max="120" step="5" bind:value={turnS}
                 disabled={!turning} aria-label="Seconds per turn" />
        {/if}
        <p class="hint">Drag to turn, scroll to zoom, right-drag to move. Hold the phone still,
          square-on to the screen.</p>
      {:else}
        <p class="hint">Click the view, then <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> to
          move, the mouse to look, <kbd>Space</kbd> up, <kbd>Shift</kbd> down, <kbd>Esc</kbd> to let go.</p>
      {/if}
    </section>

    <section>
      <div class="head">
        <h2>Lights</h2>
        <div class="seg" role="group" aria-label="Test lights">
          <button aria-pressed={lights === "off"} onclick={() => (lights = "off")}>Off</button>
          <button aria-pressed={lights === "white"} onclick={() => (lights = "white")}>White</button>
          <button aria-pressed={lights === "colours"} onclick={() => (lights = "colours")}>
            <span class="rgb" aria-hidden="true"><i></i><i></i><i></i></span>Colours</button>
        </div>
      </div>
      <p class="hint">
        {#if lights !== "off" && !testing}
          <span class="warn">Paused: <span class="mono">treemap serve</span> is sending.</span>
        {:else}
          Shown while <span class="mono">treemap serve</span> shows nothing.
        {/if}
      </p>
    </section>

    <details>
      <summary><h2>Connect treemap serve</h2></summary>
      {#if status}
        <div class="config">
          <pre class="mono">{status.controller}</pre>
          <button class="ghost" onclick={copy}>{copied ? "Copied" : "Copy"}</button>
        </div>
        <p class="hint">On <span class="mono">treemap serve</span>'s page, add a controller with
          this address.</p>
      {/if}
    </details>

    <details bind:open={layoutOpen}>
      <summary><h2>New layout</h2></summary>
      <div class="seg wide" role="group" aria-label="Shape">
        <button aria-pressed={shape === "tree"} onclick={() => (shape = "tree")}>Tree</button>
        <button aria-pressed={shape === "flat"} onclick={() => (shape = "flat")}>Flat</button>
      </div>
      <div class="grid">
        <label>LEDs <input type="number" min="1" max="5000" bind:value={leds} /></label>
        <label>Strips <input type="number" min="1" max="8" bind:value={strips} /></label>
        {#if shape === "flat"}
          <label>Pattern
            <select bind:value={pattern}>
              <option value="auto">Auto</option><option value="rows">Rows</option><option value="spiral">Spiral</option>
            </select>
          </label>
        {/if}
        <label>Seed <input type="text" inputmode="numeric" placeholder="random" bind:value={seed} /></label>
      </div>
      <button class="primary" disabled={busy || !connected} onclick={generate}>
        {busy ? "Making…" : "Make it"}
      </button>
      {#if error}<p class="hint error">{error}</p>{/if}
      {#if countChanged && !busy && !error}
        <p class="hint warn">The LED count changed: on <span class="mono">treemap serve</span>'s
          page, open this device and use the new count (its map must be scanned again).</p>
      {/if}
    </details>

    <footer>
      {#each KEYS as [k, what] (k)}<span><kbd>{k}</kbd>{what}</span>{/each}
    </footer>
  </aside>
{/if}

<style>
  :global(html), :global(body) { margin: 0; height: 100%; background: #0a0b0d; overflow: hidden; }
  :global(body) { font: 13px/1.45 var(--font); color: var(--text); }
  .view { position: fixed; inset: 0; cursor: grab; }
  .view:active { cursor: grabbing; }
  .view.walk { cursor: crosshair; }

  .panel {
    position: fixed; top: var(--s3); left: var(--s3); width: 300px; max-height: calc(100vh - 24px);
    overflow-y: auto; border-radius: var(--r2); background: rgba(17, 21, 28, 0.94);
    border: 1px solid var(--border); box-shadow: var(--shadow); backdrop-filter: blur(8px);
  }
  header { display: flex; align-items: center; justify-content: space-between; gap: var(--s3); padding: 14px 16px 0; }
  h1 { font-size: var(--t-lg); font-weight: 650; margin: 0; letter-spacing: -0.01em; }
  .sub { color: var(--muted); font-size: var(--t-sm); white-space: nowrap; }
  .source {
    padding: 2px 16px 12px; color: var(--faint); font-size: var(--t-xs); white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; border-bottom: 1px solid var(--border);
  }

  /* connection: a fixed-width badge, so changing numbers don't reflow anything */
  .badge {
    flex: none; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    min-width: 92px; height: 24px; padding: 0 10px; border-radius: 999px; box-sizing: border-box;
    font-size: var(--t-xs); font-weight: 600; white-space: nowrap;
    color: var(--warn); background: var(--warn-bg);
  }
  .badge i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
  .badge.live { color: var(--ok); background: var(--ok-bg); }
  .badge.live i { animation: pulse 1.6s ease-in-out infinite; }
  .badge.still { color: var(--info); background: var(--info-bg); }
  .badge.off { color: var(--bad); background: var(--bad-bg); }
  @keyframes pulse { 50% { opacity: 0.35; } }
  @media (prefers-reduced-motion: reduce) { .badge.live i { animation: none; } }

  section, details { padding: 12px 16px; border-bottom: 1px solid var(--border); }
  .head { display: flex; align-items: center; justify-content: space-between; gap: var(--s2); }
  h2 { font-size: var(--t-xs); font-weight: 600; margin: 0; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }
  summary { cursor: pointer; list-style: none; display: flex; align-items: center; justify-content: space-between; }
  summary::-webkit-details-marker { display: none; }
  summary::after { content: ""; width: 6px; height: 6px; border: solid var(--faint); border-width: 0 1.5px 1.5px 0; transform: rotate(-45deg); transition: transform 0.15s; }
  details[open] summary::after { transform: rotate(45deg); }
  details[open] summary { margin-bottom: 10px; }
  .hint { margin: 8px 0 0; color: var(--muted); font-size: var(--t-sm); }
  .mono { font-family: var(--mono); font-size: 0.95em; }
  .num { font-variant-numeric: tabular-nums; }

  /* a joined segmented control */
  .seg { display: inline-flex; padding: 2px; gap: 2px; border-radius: 8px; background: var(--bg); border: 1px solid var(--border); }
  .seg.wide { display: flex; }
  .seg.wide button { flex: 1; }
  .seg button {
    font: inherit; font-size: var(--t-sm); font-weight: 600; padding: 4px 10px; border: 0; border-radius: 6px;
    background: transparent; color: var(--muted); cursor: pointer; display: inline-flex; align-items: center; gap: 5px;
  }
  .seg button:hover { color: var(--text); }
  .seg button[aria-pressed="true"] { background: var(--surface-3); color: var(--text); }
  .rgb { display: inline-flex; }
  .rgb i { width: 6px; height: 6px; border-radius: 50%; margin-left: -1px; }
  .rgb i:nth-child(1) { background: #ff4d4d; }
  .rgb i:nth-child(2) { background: #3ddc84; }
  .rgb i:nth-child(3) { background: #4d8dff; }

  /* turning */
  .turn { display: flex; align-items: center; justify-content: space-between; margin-top: 12px; }
  .value { color: var(--muted); font-size: var(--t-sm); }
  .turn.on .value { color: var(--text); }
  .switch { display: inline-flex; flex-direction: row; align-items: center; color: var(--text); gap: 8px; cursor: pointer; font-size: var(--t-md); }
  .switch input { position: absolute; opacity: 0; width: 1px; height: 1px; }
  .track { width: 28px; height: 16px; border-radius: 999px; background: var(--surface-3); border: 1px solid var(--border-strong); position: relative; transition: background 0.15s; }
  .knob { position: absolute; top: 2px; left: 2px; width: 10px; height: 10px; border-radius: 50%; background: var(--muted); transition: transform 0.15s, background 0.15s; }
  .switch input:checked + .track { background: var(--accent-bg); border-color: var(--accent-border); }
  .switch input:checked + .track .knob { transform: translateX(12px); background: var(--accent); }
  .switch input:focus-visible + .track { outline: 2px solid var(--accent); outline-offset: 2px; }
  .range { width: 100%; margin: 8px 0 0; accent-color: var(--accent); }
  .range:disabled { opacity: 0.4; }

  .config { display: flex; gap: 8px; align-items: flex-start; }
  pre { flex: 1; margin: 0; padding: 8px; border-radius: var(--r1); background: var(--bg);
        border: 1px solid var(--border); font-size: var(--t-xs); white-space: pre-wrap; word-break: break-all; }
  button.ghost, button.primary {
    font: inherit; font-weight: 600; padding: 6px 12px; border-radius: var(--r1); cursor: pointer;
    border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--text);
  }
  button:disabled { opacity: 0.5; cursor: default; }
  button.primary { width: 100%; margin-top: 10px; background: var(--accent); border-color: var(--accent); color: #062016; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
  label { display: flex; flex-direction: column; gap: 3px; color: var(--muted); font-size: var(--t-sm); }
  input[type="number"], input[type="text"], select {
    font: inherit; color: var(--text); background: var(--bg); border: 1px solid var(--border-strong);
    border-radius: var(--r1); padding: 5px 8px; min-width: 0;
  }
  .error { color: var(--bad); }
  .warn { color: var(--warn); }

  footer { display: flex; flex-wrap: wrap; gap: 6px 12px; padding: 10px 16px 12px; color: var(--faint); font-size: var(--t-xs); }
  footer span { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
  kbd {
    font-family: var(--mono); font-size: 10px; min-width: 14px; text-align: center; padding: 0 4px; border-radius: 4px;
    border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--muted);
  }
</style>
