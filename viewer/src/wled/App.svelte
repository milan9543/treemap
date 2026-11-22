<script lang="ts">
  // The virtual WLED's page: the layout full screen, lit by what arrives over DDP, and a
  // panel (hidden while walking, so the phone films only the LEDs) for the status, the
  // config line for `treemap serve`, the view (rotate, optionally turning by itself, or
  // walk; see controls.ts), test lights, and new layouts.
  //
  // Test lights light the layout from this page, to look at it without the server. DDP
  // always wins: they show only while nothing arrives over DDP.
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

  let ws: WebSocket | null = null;
  let nextId = 1;

  /** Every LED white, or in the scan code's colours in turn (red, green, blue, white). */
  function testFrame(n: number, mode: Lights): ArrayBuffer {
    const f = new Uint8Array(n * 3);
    const rgb = [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]];
    for (let i = 0; i < n; i++) f.set(mode === "white" ? rgb[3] : mode === "colours" ? rgb[i % 4] : [0, 0, 0], i * 3);
    return f.buffer;
  }

  // Re-light when the switch, the layout or DDP's presence changes.
  $effect(() => {
    if (!status?.live && layout) applyFrame(testFrame(layout.led_count, lights));
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
        // the dark frame after DDP stops doesn't put the test lights out
        if (status?.live || lights === "off") applyFrame(ev.data);
        return;
      }
      const m = JSON.parse(ev.data);
      if (m.type === "status") status = m;
      else if (m.type === "layout") void loadLayout();
      else if (m.type === "generated") {
        busy = false;
        error = m.ok ? null : m.error;
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
      await navigator.clipboard.writeText(`output: wled\n${status.controller}\n`);
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
    else if (e.code === "Space" && mode === "rotate") {
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
      <h1>Virtual WLED</h1>
      <span class="dot" class:live={status?.live} class:off={!connected}></span>
    </header>

    {#if !connected}
      <p class="muted">Reconnecting to <span class="mono">treemap sim wled</span>…</p>
    {:else if status}
      <p>
        <b class="num">{status.led_count}</b> LEDs, {status.shape}.
        {#if status.live}
          Receiving <span class="num">{status.fps}</span> fps from <span class="mono">{status.source}</span>.
        {:else}
          <span class="muted">Waiting for <span class="mono">treemap serve</span>.</span>
        {/if}
      </p>
      <div class="config">
        <pre class="mono">output: wled
{status.controller}</pre>
        <button class="small" onclick={copy}>{copied ? "Copied" : "Copy"}</button>
      </div>
      <p class="muted small">Put these in <span class="mono">config.local.yaml</span>, then start
        <span class="mono">treemap serve</span>.</p>
    {/if}

    <h2>Test lights</h2>
    <div class="seg three" role="group" aria-label="Test lights">
      <button aria-pressed={lights === "off"} onclick={() => (lights = "off")}>Off</button>
      <button aria-pressed={lights === "white"} onclick={() => (lights = "white")}>White</button>
      <button aria-pressed={lights === "colours"} onclick={() => (lights = "colours")}>Colours</button>
    </div>
    <p class="muted small">
      {#if lights !== "off" && status?.live}
        Showing <span class="mono">treemap serve</span>'s colours: the test lights come back when it stops.
      {:else}
        Lights the LEDs from here, while <span class="mono">treemap serve</span> sends nothing.
        <kbd>L</kbd> switches them, even with this panel hidden.
      {/if}
    </p>

    <h2>New layout</h2>
    <div class="seg" role="group" aria-label="Shape">
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
    {#if error}<p class="error">{error}</p>{/if}
    {#if countChanged && !busy && !error}
      <p class="warn small">The LED count changed: restart <span class="mono">treemap serve</span>
        so it reads the new count.</p>
    {/if}

    <h2>View</h2>
    <div class="seg" role="group" aria-label="View">
      <button aria-pressed={mode === "rotate"} onclick={() => switchMode("rotate")}>Rotate</button>
      <button aria-pressed={mode === "walk"} onclick={() => switchMode("walk")}>Walk</button>
    </div>
    {#if mode === "rotate"}
      {#if layout?.shape !== "flat"}
        <label class="row">
          <input type="checkbox" bind:checked={turning} /> Turn by itself
        </label>
        <label class="slider" class:off={!turning}>
          <span>Once round in <b class="num">{turnS}</b> s</span>
          <input type="range" min="10" max="120" step="5" bind:value={turnS} disabled={!turning} />
        </label>
      {/if}
      <p class="muted small">Drag to turn round it, scroll to zoom, right-drag to move.
        <kbd>Space</kbd> starts or stops the turning. Hold the phone still in front of the
        screen, square-on, with the layout in the middle.</p>
    {:else}
      <p class="muted small">Click the view, then <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd>
        to move, the mouse to look, <kbd>Space</kbd> up, <kbd>Shift</kbd> down. <kbd>Esc</kbd>
        lets go of the mouse. Film the screen square-on, with the layout in the middle.</p>
    {/if}
    <p class="muted small"><kbd>M</kbd> switches rotate and walk, <kbd>R</kbd> goes back to
      the start, <kbd>H</kbd> hides this panel, <kbd>L</kbd> switches the test lights.</p>
  </aside>
{/if}

<style>
  :global(html), :global(body) { margin: 0; height: 100%; background: #0a0b0d; overflow: hidden; }
  :global(body) { font: 13px/1.45 var(--font); color: var(--text); }
  .view { position: fixed; inset: 0; cursor: grab; }
  .view.walk { cursor: crosshair; }
  label.row { flex-direction: row; align-items: center; gap: 8px; color: var(--text); font-size: inherit; margin-top: 10px; }
  label.slider { margin-top: 6px; }
  label.slider.off { opacity: 0.5; }
  input[type="range"], input[type="checkbox"] { padding: 0; accent-color: var(--accent); }
  .panel {
    position: fixed; top: 12px; left: 12px; width: 320px; max-height: calc(100vh - 24px);
    overflow-y: auto; padding: 14px 16px; border-radius: var(--r2);
    background: rgba(17, 21, 28, 0.92); border: 1px solid var(--border); box-shadow: var(--shadow);
  }
  header { display: flex; align-items: center; justify-content: space-between; }
  h1 { font-size: var(--t-xl); margin: 0; }
  h2 { font-size: var(--t-md); margin: 16px 0 8px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  p { margin: 8px 0; }
  .muted { color: var(--muted); }
  .small { font-size: var(--t-sm); }
  .mono { font-family: var(--mono); }
  .num { font-variant-numeric: tabular-nums; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--warn); }
  .dot.live { background: var(--ok); }
  .dot.off { background: var(--bad); }
  .config { display: flex; gap: 8px; align-items: flex-start; }
  pre { flex: 1; margin: 0; padding: 8px; border-radius: var(--r1); background: var(--surface-2);
        border: 1px solid var(--border); font-size: var(--t-sm); white-space: pre-wrap; word-break: break-all; }
  button {
    font: inherit; font-weight: 600; padding: 7px 12px; border-radius: var(--r1); cursor: pointer;
    border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--text);
  }
  button:disabled { opacity: 0.5; cursor: default; }
  button.primary { width: 100%; margin-top: 10px; background: var(--accent); border-color: var(--accent); color: #062016; }
  .seg { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .seg.three { grid-template-columns: 1fr 1fr 1fr; }
  .seg button[aria-pressed="true"] { border-color: var(--accent-border); background: var(--accent-bg); }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; }
  label { display: flex; flex-direction: column; gap: 3px; color: var(--muted); font-size: var(--t-sm); }
  input, select {
    font: inherit; color: var(--text); background: var(--surface-2); border: 1px solid var(--border-strong);
    border-radius: var(--r1); padding: 6px 8px; min-width: 0;
  }
  .error { color: var(--bad); }
  .warn { color: var(--warn); }
  kbd {
    font-family: var(--mono); font-size: 11px; padding: 0 4px; border-radius: 4px;
    border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--text);
  }
</style>
