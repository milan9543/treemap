<script lang="ts">
  // Step 3: look over the map, fix what's wrong, and set which way it faces.
  //
  // Missing and guessed LEDs are listed in runs along the strip; tapping one lights it
  // blue on the tree, and "Scan this part again" goes back to the scan, keeping the
  // rounds so far. An LED in the wrong place (it lights out of step in a rising plane)
  // can have its readings ignored, so it's filled from its neighbours. Then the front
  // (tree: a white stripe the user turns to face the room) or the bottom (flat: the
  // bottom edge white, the left side red; turn and mirror until they're right) is shown
  // on the LEDs as it changes, and saved with the map. Every effect follows it.
  import { onDestroy, onMount } from "svelte";
  import LedStatus from "../components/LedStatus.svelte";
  import TopBar from "../components/TopBar.svelte";
  import { ApiError, type Api, type MapInfo } from "../lib/api";
  import { app } from "../lib/state.svelte";

  let { api }: { api: Api } = $props();

  const BLUE = [0, 60, 255];
  const MAX_RUNS = 40;

  type Run = { from: number; to: number; missing: boolean };

  let map = $state<MapInfo | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let onLeds = $state<string | null>(null); // what this page put on the LEDs
  let picked = $state<Run | null>(null);
  let index = $state(0);
  let solving = $state(false);
  let solved = $state<string | null>(null);
  let front = $state(0);
  let rotate = $state<0 | 90 | 180 | 270>(0);
  let mirror = $state(false);
  let saving = $state(false);
  let savedNote = $state(false);

  const flat = $derived(map?.shape === "flat");
  const n = $derived(map?.led_count ?? 0);
  const runs = $derived(map ? findRuns(map.led_status) : []);
  const ignored = $derived(map?.ignored.includes(index) ?? false);
  const dirty = $derived.by(() => {
    const o = map?.orientation;
    if (!o) return false;
    return "front_deg" in o ? Math.round(o.front_deg) !== front
      : o.rotate_deg !== rotate || o.mirror !== mirror;
  });

  /** Runs of LEDs that aren't ok, in strip order; a run with a failed LED is missing. */
  function findRuns(status: string): Run[] {
    const out: Run[] = [];
    for (let i = 0; i < status.length; i++) {
      if (status[i] === "o") continue;
      const last = out[out.length - 1];
      if (last && last.to === i - 1) {
        last.to = i;
        last.missing ||= status[i] === "f";
      } else {
        out.push({ from: i, to: i, missing: status[i] === "f" });
      }
    }
    return out;
  }

  const span = (r: Run) => (r.from === r.to ? `${r.from}` : `${r.from}–${r.to}`);

  function useMap(m: MapInfo) {
    map = m;
    const o = m.orientation;
    if ("front_deg" in o) front = Math.round(o.front_deg) % 360;
    else {
      rotate = o.rotate_deg;
      mirror = o.mirror;
    }
  }

  async function load() {
    loading = true;
    try {
      useMap(await api.map());
      error = null;
    } catch (e) {
      error = (e as ApiError).status === 404 ? null : (e as Error).message;
      map = null;
    } finally {
      loading = false;
    }
  }

  // LED commands, latest wins: a slider sends many, the LEDs show the last.
  let sending = false;
  let queued: Record<string, unknown> | null = null;

  async function show(cmd: Record<string, unknown>, what: string) {
    onLeds = what;
    queued = cmd;
    if (sending) return;
    sending = true;
    while (queued) {
      const c = queued;
      queued = null;
      try {
        await api.leds(c);
        error = null;
      } catch (e) {
        error = (e as Error).message;
      }
    }
    sending = false;
  }

  async function play(effect: string, params: Record<string, unknown>, what: string) {
    try {
      await api.play(effect, params);
      onLeds = what;
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  // -- fixing -------------------------------------------------------------------------

  function pickRun(r: Run) {
    picked = r;
    void show({ mode: "led", index: r.from, to: r.to, color: BLUE, neighbours: true }, "run");
  }

  function scanAgain() {
    app.shape = map!.shape;
    app.addRounds = true;
    app.screen = "scan";
  }

  function lightOne(i: number) {
    index = Math.min(Math.max(0, Math.round(i) || 0), n - 1);
    solved = null;
    void show({ mode: "led", index, color: BLUE, neighbours: true }, "one");
  }

  async function setIgnored(ignore: boolean) {
    solving = true;
    solved = null;
    error = null;
    const i = index;
    try {
      useMap(await api.interpolate(i, ignore));
      const letter = map!.led_status[i];
      solved = ignore ? `LED ${i} is now ${letter === "f" ? "a rough guess" : "filled in from its neighbours"}.`
        : `LED ${i} uses its readings again.`;
      app.info = await api.info().catch(() => app.info);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      solving = false;
    }
  }

  // -- facing the room ------------------------------------------------------------------

  function showFront() {
    void show({ mode: "stripe", front_deg: front }, "orientation");
  }

  function showEdge() {
    void show({ mode: "edge", rotate_deg: rotate, mirror }, "orientation");
  }

  function turnFront(deg: number) {
    front = (((front + deg) % 360) + 360) % 360;
    showFront();
  }

  function turnFlat() {
    rotate = ((rotate + 90) % 360) as 0 | 90 | 180 | 270;
    showEdge();
  }

  function flip() {
    mirror = !mirror;
    showEdge();
  }

  async function save() {
    saving = true;
    try {
      useMap(await api.setOrientation(flat ? { rotate_deg: rotate, mirror } : { front_deg: front }));
      savedNote = true;
      error = null;
      app.info = await api.info().catch(() => app.info);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  function tryIt() {
    if (onLeds === "try") return void off();
    void play("plane", flat ? { direction: "up", speed: 0.3, color: "gold" }
      : { direction: "around", speed: 0.15, color: "gold" }, "try");
  }

  function risingPlane() {
    if (onLeds === "plane") return void off();
    void play("plane", { direction: "up", speed: 0.2, color: "white" }, "plane");
  }

  async function off() {
    await show({ mode: "off" }, "off");
    onLeds = null;
  }

  onMount(load);

  onDestroy(() => {
    // everything this screen shows is a check: leaving it turns the LEDs off
    if (onLeds) void api.leds({ mode: "off" }).catch(() => {});
  });

  const date = (iso: string | null) =>
    iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
</script>

<main class="page">
  <TopBar title="Review the map" step="Step 3 of 3" back="connect" />

  {#if loading}
    <p class="muted">Loading the map…</p>
  {:else if !map}
    <section class="card">
      <h2>No map yet</h2>
      <p class="muted small">Scan the {app.shape === "flat" ? "LEDs" : "tree"} first.</p>
      <button class="primary wide" onclick={() => (app.screen = "scan")}>Go to the scan</button>
    </section>
  {:else}
    <section class="card">
      <h2>The map</h2>
      <p class="small muted">{map.shape === "flat" ? "A flat layout" : "A tree"} of {n} LEDs{map.rounds
        ? `, from ${map.rounds} round${map.rounds === 1 ? "" : "s"}` : ""}{map.created ? `, ${date(map.created)}` : ""}.</p>
      <LedStatus counts={map.counts} status={map.led_status} />
      <div class="actions">
        <button disabled={onLeds === "status"} onclick={() => show({ mode: "status" }, "status")}>
          {onLeds === "status" ? "On the LEDs" : "Show on the LEDs"}</button>
      </div>
    </section>

    {#if runs.length}
      <section class="card">
        <h2>Missing and guessed LEDs</h2>
        <p class="small muted">Tap one to light it blue on the {flat ? "LEDs" : "tree"}, with
          its neighbours dim white. Guessed LEDs (yellow) sit between found ones and are
          usually close; missing ones (red) are only a rough guess.</p>
        <div class="runs">
          {#each runs.slice(0, MAX_RUNS) as r (r.from)}
            <button class="chip num" class:on={picked?.from === r.from} onclick={() => pickRun(r)}
                    aria-label="{r.missing ? 'Missing' : 'Guessed'}: LED {span(r)}">
              <i class="dot" class:missing={r.missing}></i>{span(r)}
            </button>
          {/each}
          {#if runs.length > MAX_RUNS}
            <span class="small muted more">and {runs.length - MAX_RUNS} more</span>
          {/if}
        </div>
        {#if picked}
          <p class="small picked">
            {picked.from === picked.to ? `LED ${picked.from} is` : `LEDs ${span(picked)} are`} blue.
            To find {picked.from === picked.to ? "it" : "them"}, scan that part again:
            point the phone there for a round or two. The rounds so far are kept.
          </p>
        {/if}
        <button class="primary wide" onclick={scanAgain}>Scan {picked ? "this part" : "parts"} again</button>
      </section>
    {/if}

    <section class="card">
      <h2>An LED in the wrong place?</h2>
      <p class="small muted">Run a plane up the {flat ? "LEDs" : "tree"}: an LED that lights out
        of step with those round it is in the wrong place. Find its number, then ignore its
        readings so it's filled in from its neighbours.</p>
      <button class="wide" onclick={risingPlane}>
        {onLeds === "plane" ? "Stop the plane" : "Run a rising plane"}</button>
      <div class="stepper">
        <button aria-label="Previous LED" disabled={index <= 0 || solving} onclick={() => lightOne(index - 1)}>−</button>
        <input type="number" inputmode="numeric" min="0" max={n - 1} aria-label="LED number"
               value={index} disabled={solving} onchange={(e) => lightOne(Number(e.currentTarget.value))} />
        <button aria-label="Next LED" disabled={index >= n - 1 || solving} onclick={() => lightOne(index + 1)}>+</button>
      </div>
      <div class="actions">
        <button disabled={solving} onclick={() => lightOne(index)}>
          {onLeds === "one" ? `LED ${index} is blue` : "Light it"}</button>
        <button class={ignored ? "" : "danger"} disabled={solving} onclick={() => setIgnored(!ignored)}>
          {solving ? "Solving…" : ignored ? "Use its readings" : "Ignore its readings"}</button>
      </div>
      {#if solving}
        <p class="small muted after">Solving the map again; this can take a minute.</p>
      {:else if solved}
        <div class="note ok">{solved}</div>
      {/if}
    </section>

    <section class="card">
      {#if flat}
        <h2>Set the bottom</h2>
        <p class="small muted">The LEDs show the layout's bottom edge in white and its left side
          in red. Turn it until the white is along the bottom. If the red is then on the right,
          mirror it: the LEDs were filmed from behind.</p>
        <div class="actions">
          <button onclick={turnFlat}>Turn ↺ 90°</button>
          <button aria-pressed={mirror} class:pressed={mirror} onclick={flip}>Mirror</button>
        </div>
        <p class="small muted num after">
          {onLeds === "orientation" ? "On the LEDs: " : ""}turned {rotate}°{mirror ? ", mirrored" : ""}
          {#if onLeds !== "orientation"}· <button class="link" onclick={showEdge}>show it</button>{/if}
        </p>
      {:else}
        <h2>Set the front</h2>
        <p class="small muted">A white stripe lights the LEDs that face the front. Turn it until
          it faces the room, where people see the tree from. Effects that go round the tree
          start there.</p>
        <input class="slider" type="range" min="0" max="359" step="1" aria-label="Front, in degrees"
               bind:value={front} oninput={showFront} />
        <div class="turns">
          <button aria-label="Turn back 10 degrees" onclick={() => turnFront(-10)}>−10°</button>
          <span class="num deg">{front}°</span>
          <button aria-label="Turn on 10 degrees" onclick={() => turnFront(10)}>+10°</button>
        </div>
        {#if onLeds !== "orientation"}
          <button class="wide" onclick={showFront}>Show the stripe</button>
        {/if}
      {/if}
      <div class="actions">
        <button class="primary" disabled={!dirty || saving} onclick={save}>
          {saving ? "Saving…" : dirty ? `Save the ${flat ? "bottom" : "front"}` : "Saved"}</button>
        <button onclick={tryIt}>{onLeds === "try" ? "Stop"
          : flat ? "Try: rising plane" : "Try: beam from the front"}</button>
      </div>
      {#if savedNote && !dirty}
        <p class="small muted after">Every effect now uses this {flat ? "bottom" : "front"}.</p>
      {/if}
    </section>
  {/if}

  {#if error}<div class="note bad">{error}</div>{/if}

  <button class="link" onclick={() => { app.addRounds = false; app.screen = "scan"; }}>Scan from scratch</button>
</main>

<style>
  .wide { width: 100%; margin-top: 4px; }
  .after { margin: 10px 0 0; }
  .runs { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 8px; }
  .chip {
    min-height: 36px; padding: 4px 12px; border-radius: 999px; font-size: 13px;
    display: inline-flex; align-items: center; gap: 6px;
  }
  .chip.on { border-color: var(--accent); background: var(--accent-bg); }
  .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; background: var(--warn); }
  .dot.missing { background: var(--bad); }
  .more { align-self: center; }
  .picked { margin: 6px 0 4px; }
  .stepper { display: grid; grid-template-columns: 56px 1fr 56px; gap: 8px; margin-top: 12px; }
  .stepper button { font-size: 22px; padding: 0; }
  .stepper input { text-align: center; font-variant-numeric: tabular-nums; }
  .slider { width: 100%; height: 40px; accent-color: var(--accent); }
  .turns { display: grid; grid-template-columns: 1fr auto 1fr; gap: 8px; align-items: center; margin: 4px 0 8px; }
  .deg { font-size: 20px; font-weight: 650; min-width: 4ch; text-align: center; }
  .pressed { border-color: var(--accent); background: var(--accent-bg); }
</style>
