<script lang="ts">
  // Step 2: film the LEDs while the server flashes their codes, round after round.
  //
  // The server runs the scan (countdown, then rounds of flashing, solving and showing the
  // result on the LEDs) and this page films for it: frames go up every 250 ms for as
  // long as the scan runs, and its state is polled once a second. When the server
  // reaches the "exposure" phase, the page sets the camera's exposure for the LEDs
  // (exposure.ts: found automatically, or the one last used with this camera), then
  // lets the user tap another exposure to try it; Continue tells the server it's done,
  // and the server measures the colours. Between rounds the LEDs show the result until
  // the user, now standing where it's red, starts the next round.
  import { onDestroy, onMount } from "svelte";
  import ExposurePicker from "../components/ExposurePicker.svelte";
  import LedStatus from "../components/LedStatus.svelte";
  import { ApiError, type Api, type Phase, type ScanState } from "../lib/api";
  import { cameraName, openRearCamera, type Camera } from "../lib/camera";
  import {
    autoExposure, cameraId, cameraSettings, canSetExposure, describe, Gone, saveExposure,
    savedExposure, setExposure, stepName, tryStep, useExposure, type Exposure, type Probe, type Step,
  } from "../lib/exposure";
  import { app } from "../lib/state.svelte";
  import { Uploader } from "../lib/uploader.svelte";

  let { api }: { api: Api } = $props();

  let video = $state<HTMLVideoElement>();
  let cam = $state<Camera | null>(null);
  let camError = $state<string | null>(null);
  let st = $state<ScanState | null>(null);
  let mine = $state<number | null>(null); // the scan this page follows
  let starting = $state(false);
  let stopping = $state(false);
  let error = $state<string | null>(null);
  let shown = $state(false); // the result is on the LEDs
  let total = $state(0); // seconds the current phase lasts, for its bar
  let phaseKey = "";
  let exposingFor: number | null = null; // the scan whose exposure this page has set (or is setting)
  let steps = $state<Step[]>([]); // the exposures tried, and the LEDs each showed
  let autoChosen = $state<number | null>(null); // the one the search (or "last used") picked
  let exposure = $state<Exposure | null>(null);
  let problem = $state<string | null>(null); // the exposure couldn't be set
  let picking = $state(false); // waiting for the user to keep this exposure or try another
  // while searching: the step being counted (the first not tried yet)
  const searching = $derived(picking ? null : (() => {
    const i = steps.findIndex((s) => s.leds === null);
    return i < 0 ? null : i;
  })());
  let touched = $state(false); // they tried another exposure
  let going = $state(false); // asked for the next round, waiting for it to start
  let trying = $state<number | null>(null); // the step being tried
  let camId = $state<string | null>(null);
  let lastUsed = $state<{ ms: number; iso: number | null } | null>(null);
  let useLast = $state(false);
  let howFound = "";
  let alive = true;
  let polling = false;
  let wake: WakeLockSentinel | null = null;
  const up = new Uploader(app.api!); // the screen is only shown with a server
  const n = app.info?.led_count ?? 0;

  const view = $derived(mine === null ? "ready"
    : !st || st.id !== mine || st.status === "running" ? "scanning" : "finished");

  const LABELS: Record<Phase, string> = {
    countdown: "Get ready",
    exposure: "Setting the exposure",
    colours: "Measuring the colours",
    flashing: "Flashing codes",
    solving: "Working out positions",
    status: "Result",
  };

  function hint(phase: Phase | null, waiting = false): string {
    const tree = app.shape === "tree";
    switch (phase) {
      case "flashing":
        return tree ? "Walk slowly round the tree, all of it in view." : "Keep every LED in view, phone steady.";
      case "solving":
        return "Keep the camera on the LEDs.";
      case "exposure":
        return "Hold still with all the LEDs in view.";
      case "colours":
        return "Keep holding still.";
      case "status":
        if (waiting) {
          return tree ? "Walk to the red part, then start the next round."
            : "Make sure nothing hides the red LEDs, then start the next round.";
        }
        return tree ? "Walk to the red part: the next round starts in a moment."
          : "Make sure nothing hides the red LEDs: the next round starts in a moment.";
      default:
        return "Point the camera at the LEDs, all of them in view.";
    }
  }

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  // -- camera -------------------------------------------------------------------------

  async function openCamera() {
    camError = null;
    try {
      const c = await openRearCamera();
      if (!alive) {
        c.stream.getTracks().forEach((t) => t.stop());
        return;
      }
      cam = c;
      camId = await cameraId(c.label);
      lastUsed = canSetExposure(c.track) ? savedExposure(camId) : null;
      video!.srcObject = c.stream;
      await video!.play().catch(() => {});
      film();
    } catch (e) {
      const name = (e as DOMException).name;
      camError = name === "NotAllowedError"
        ? "The camera is blocked. Tap the icon left of the address bar, allow the camera, and try again."
        : name === "NotFoundError" ? "This device has no camera."
        : `The camera didn't open: ${(e as Error).message}`;
    }
  }

  /** Upload while following a running scan, with the camera open. */
  function film() {
    if (cam && video && mine !== null && view === "scanning") up.start(cam.track, video);
  }

  async function keepAwake() {
    try {
      wake = (await navigator.wakeLock?.request("screen")) ?? null;
    } catch {
      wake = null; // not allowed (battery saver): the screen may dim
    }
  }

  function onVisible() {
    if (document.visibilityState === "visible" && view === "scanning" && !wake) void keepAwake();
  }

  // -- the scan -----------------------------------------------------------------------

  async function start() {
    starting = true;
    error = null;
    shown = false;
    try {
      const { id } = await api.scanStart({ shape: app.shape, camera: camId ?? undefined,
                                           add: app.addRounds || undefined });
      st = null;
      phaseKey = "";
      steps = [];
      exposure = null;
      problem = null;
      follow(id);
      void keepAwake();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      starting = false;
    }
  }

  function follow(id: number) {
    mine = id;
    stopping = false;
    film();
    void poll();
  }

  async function poll() {
    if (polling) return;
    polling = true;
    while (alive && mine !== null) {
      try {
        const s = await api.scanState();
        if (s.id !== mine) {
          error = "The scan ended on the server (was it restarted?).";
          await finish();
          break;
        }
        const key = `${s.round}/${s.phase}`;
        if (key !== phaseKey) {
          phaseKey = key;
          total = s.remaining ?? 0;
        } else if ((s.remaining ?? 0) > total) {
          total = s.remaining!;
        }
        st = s;
        error = null;
        if (!s.waiting) going = false;
        if (s.status === "running" && s.phase === "exposure" && exposingFor !== s.id) {
          void setUp(s.id);
        }
        if (s.status !== "running") {
          await finish();
          break;
        }
      } catch (e) {
        error = (e as ApiError).status === 0 ? "Lost the server; still trying…" : (e as Error).message;
      }
      await sleep(1000);
    }
    polling = false;
  }

  /** The server waits in the "exposure" phase, the LEDs in the code's colours, for this. */
  async function setUp(id: number) {
    exposingFor = id;
    steps = [];
    exposure = null;
    problem = null;
    try {
      if (!cam) throw new Error("The camera is off.");
      const p = probe(id);
      const last = useLast ? lastUsed : null;
      howFound = last ? "last used" : "found automatically";
      const r = last ? await useExposure(cam.track, last) : await setExposure(cam.track, p);
      exposure = r;
      steps = r.steps;
      autoChosen = r.chosen;
      if (r.chosen === null) { // nothing to choose from: auto exposure, locked or not
        if (!r.ok) problem = r.message;
        await ready({ message: r.message, settings: r.settings });
        return;
      }
      if (!r.ok) problem = r.message;
      if (last) await tryChosen(r.chosen, p); // its count, for comparison
      startPicking();
    } catch (e) {
      if (e instanceof Gone || (e as ApiError).status === 409) return; // the scan moved on
      const msg = (e as Error).message;
      problem = `Couldn't set the exposure: ${msg}`;
      await ready({ message: `the page couldn't set the exposure: ${msg}`,
                    settings: cam ? cameraSettings(cam.track) : {} });
    }
  }

  function probe(id: number): Probe {
    return {
      probe: (since) => api.exposureProbe(since),
      ledCount: n,
      mark: () => up.mark(),
      onStep: (s) => (steps = s),
      alive: () => alive && mine === id && !stopping,
    };
  }

  function startPicking() {
    picking = true;
    touched = false;
  }

  function stopPicking() {
    picking = false;
    trying = null;
  }

  async function tryChosen(i: number, p: Probe) {
    trying = i;
    try {
      const tried = await tryStep(cam!.track, steps[i], p);
      steps = steps.map((s, j) => (j === i ? tried : s));
      exposure = { ...exposure!, steps, chosen: i, ok: true, settings: cameraSettings(cam!.track) };
      problem = null;
    } finally {
      trying = null;
    }
  }

  /** Try another exposure: the preview and its count follow. */
  async function pick(i: number) {
    if (!picking || trying !== null || !cam || mine === null) return;
    touched = true;
    try {
      await tryChosen(i, probe(mine));
    } catch (e) {
      if (!(e instanceof Gone)) error = (e as Error).message;
    }
  }

  /** Keep the exposure that's set and go on to the colours. */
  async function keep() {
    if (!picking || !exposure || exposure.chosen === null || !cam) return;
    stopPicking();
    const s = exposure.steps[exposure.chosen];
    if (camId && s.leds) saveExposure(camId, s);
    const how = touched ? "picked by hand" : howFound;
    await ready({ message: describe(exposure, how), settings: cameraSettings(cam.track) });
  }

  async function ready(done: { message: string; settings: Record<string, unknown> }) {
    try {
      await api.cameraReady(done); // the scan goes on, even after a failure
    } catch (e) {
      if ((e as ApiError).status !== 409) error = (e as Error).message;
    }
  }

  async function finish() {
    stopPicking();
    if (cam) void autoExposure(cam.track); // a brighter preview between scans
    if (camId && cam && canSetExposure(cam.track)) lastUsed = savedExposure(camId);
    await up.stop();
    await wake?.release().catch(() => {});
    wake = null;
    try {
      app.info = await api.info();
    } catch {
      /* shown on the next connect */
    }
  }

  /** Between rounds: start the next one, or finish with the rounds so far. */
  async function next(finish: boolean) {
    going = true;
    try {
      await api.scanNext(finish); // stays "going" until the poll sees the next round
    } catch (e) {
      error = (e as Error).message;
      going = false;
    }
  }

  async function stop() {
    stopping = true;
    try {
      await api.scanStop();
    } catch (e) {
      error = (e as Error).message;
      stopping = false;
    }
  }

  async function showResult() {
    try {
      await api.leds({ mode: "status" });
      shown = true;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  function again() {
    mine = null;
    st = null;
    shown = false;
    app.addRounds = false;
  }

  function review() {
    app.addRounds = false;
    app.screen = "review";
  }

  onMount(async () => {
    document.addEventListener("visibilitychange", onVisible);
    void openCamera();
    try {
      const s = await api.scanState();
      if (s.status === "running") { // picked up after a reload
        st = s;
        follow(s.id);
        void keepAwake();
      }
    } catch (e) {
      error = (e as Error).message;
    }
  });

  onDestroy(() => {
    alive = false;
    document.removeEventListener("visibilitychange", onVisible);
    up.dispose();
    cam?.stream.getTracks().forEach((t) => t.stop());
    void wake?.release().catch(() => {});
  });

  // Between rounds: the next round's button takes the focus as it appears.
  let nextBtn = $state<HTMLButtonElement>();
  const waiting = $derived(!!st?.waiting); // changes only as the wait starts or ends
  $effect(() => {
    if (waiting) nextBtn?.focus();
  });
  let messageOpen = $state(false); // a long message is cut to two lines until tapped

  const progress = $derived(total > 0 && st?.remaining != null ? 1 - st.remaining / total : null);
  const roundLabel = $derived(!st || !st.round ? "Getting ready" : `Round ${st.round}`);
  const canFinish = $derived(st?.phase === "status");
</script>

<div class="scan">
  <div class="viewport">
    <!-- svelte-ignore a11y_media_has_caption -->
    <video bind:this={video} playsinline muted autoplay></video>

    <div class="overlay top">
      {#if view !== "scanning"}
        <button class="round-btn" aria-label="Back" onclick={() => (app.screen = "connect")}>
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            <path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2.2"
                  stroke-linecap="round" stroke-linejoin="round" /></svg>
        </button>
      {/if}
      {#if view === "scanning"}
        <div class="pill">
          <span class="rec" class:live={up.running}></span>
          {roundLabel + (st?.phase ? ` · ${LABELS[st.phase]}` : "")}
        </div>
      {/if}
    </div>

    {#if view === "scanning" && st?.phase === "countdown" && st.remaining}
      <div class="countdown num" aria-live="polite">{Math.ceil(st.remaining)}</div>
    {/if}

    {#if !cam}
      <div class="cam-msg">
        {#if camError}
          <p>{camError}</p>
          <button onclick={openCamera}>Try again</button>
        {:else}
          <p class="muted">Opening the camera…</p>
        {/if}
      </div>
    {/if}

    {#if cam}
      <div class="overlay bottom small num">
        <span>{cameraName(cam.label)} · {cam.width}×{cam.height}</span>
        {#if up.running}<span>sending {up.fps} fps</span>{/if}
      </div>
    {/if}
  </div>

  <section class="panel" class:compact={view === "scanning"}>
    {#if view === "ready" && app.addRounds}
      <div class="step">Step 3 of 3</div>
      <h2>Scan parts again</h2>
      <p class="muted small">
        The rounds so far are kept, and each new round adds to them. Point the phone at the
        part that's missing{app.shape === "tree" ? ", walking round to it if it's at the back" : ""}.
        After each round the LEDs show what's found: green found, yellow guessed, red missing.
      </p>
      <button class="link" onclick={() => (app.addRounds = false)}>Scan from scratch instead</button>
    {:else if view === "ready"}
      <div class="step">Step 2 of 3</div>
      <h2>Scan the {app.shape === "flat" ? "LEDs" : "tree"}</h2>
      <p class="muted small">
        {#if app.shape === "tree"}
          Stand where you can see the whole tree. Once it starts, the LEDs glow white for a
          few seconds, then flash their codes while you walk slowly round it. After each round
          the tree shows what was found; walk to the red parts and start the next round, until
          every LED is found.
        {:else}
          Hold the phone so every LED is in view, as square-on as you can. The LEDs glow white
          for a few seconds, then flash their codes; after each round they show what was
          found, and you start the next round when you're ready.
        {/if}
      </p>
    {/if}
    {#if view === "ready"}
      {#if app.info?.map?.fits && !app.addRounds}
        <p class="small muted">This replaces the current map.</p>
      {/if}
      {#if lastUsed}
        <label class="check small">
          <input type="checkbox" bind:checked={useLast} />
          <span>Use the last exposure ({stepName(lastUsed)}) instead of finding it again</span>
        </label>
      {/if}
      <button class="primary wide" disabled={!cam || starting} onclick={start}>
        {starting ? "Starting…" : "Start the scan"}
      </button>

    {:else if view === "scanning"}
      <div class="phase-head">
        <h2>{st?.phase ? LABELS[st.phase] : "Starting"}</h2>
        {#if st?.phase === "flashing" || st?.phase === "status" || st?.phase === "solving"}
          <span class="small muted num">{st.identified ?? 0} of {n} read</span>
        {/if}
      </div>
      <div class="bar" aria-hidden="true">
        <div style:width="{progress === null ? 0 : Math.min(100, 100 * progress)}%"></div>
      </div>
      <p class="hint">{hint(st?.phase ?? null, st?.waiting)}</p>
      {#if st?.phase === "exposure" && steps.length}
        <ExposurePicker {steps} {picking} ledCount={n} auto={autoChosen}
                        chosen={picking ? (exposure?.chosen ?? null) : null}
                        trying={picking ? trying : searching} onpick={pick} />
        {#if picking}
          <p class="small muted">Tap a bar to try that exposure: brighter shows dim LEDs,
            darker keeps the colours clean.</p>
          <button class="primary wide" disabled={trying !== null} onclick={keep}>
            {touched ? "Use this exposure" : "Continue"}
          </button>
        {/if}
      {/if}
      {#if problem && st?.round === 0}
        <p class="line warn">{problem}</p>
      {/if}
      {#if st?.colours && st.phase === "colours"}
        <div class="colours num small">
          {#each Object.entries(st.colours.read_right) as [name, share] (name)}
            <span class:low={share === null || share < 0.85}>
              <i class="dot {name}"></i>{share === null ? "unseen" : `${Math.round(share * 100)}%`}
            </span>
          {/each}
        </div>
        {#if !st.colours.ok}
          <p class="line warn">Some colours are hard to tell apart.{#each st.colours.tips as tip (tip)}
            {" " + tip}{/each}</p>
        {/if}
      {:else if st?.colours && !st.colours.ok}
        <p class="line warn">Colours are hard to tell apart: LEDs may be misread.</p>
      {/if}
      {#if st?.phase === "status" && !st.identified}
        <p class="line warn">No LED was read this round. Is the camera on the flashing LEDs?
          Try standing closer.</p>
      {:else if st?.phase === "status"}
        <LedStatus counts={st.counts} status={st.led_status} compact />
      {/if}
      {#if st?.message && st.message !== "stopping…" && !(st.phase === "status" && !st.identified)}
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
        <p class="line" class:open={messageOpen} onclick={() => (messageOpen = !messageOpen)}>{st.message}</p>
      {/if}
      {#if up.error}
        <div class="note bad">Frames aren't reaching the server: {up.error}</div>
      {:else if !cam}
        <div class="note warn">The camera is off, so nothing is being filmed.</div>
      {/if}
      {#if st?.waiting}
        <div class="row">
          <button class="primary" bind:this={nextBtn} disabled={going} onclick={() => next(false)}>
            {going ? "Starting…" : `Start round ${(st.round ?? 0) + 1}`}
          </button>
          <button disabled={going} onclick={() => next(true)}>Finish here</button>
        </div>
      {:else}
        <button class="wide {canFinish ? 'primary' : 'danger'}" disabled={stopping} onclick={stop}>
          {stopping ? "Stopping…" : canFinish ? "Finish here" : "Stop"}
        </button>
      {/if}

    {:else if st}
      {#if st.status === "done" || st.status === "cancelled"}
        <h2>Scan {st.status === "done" ? "finished" : "stopped"}</h2>
        <p class="muted small">
          {#if !st.led_status}
            The map wasn't changed: no finished round found any LEDs.
          {:else if st.status === "done"}
            The map is saved on the server.
          {:else}
            The map from the rounds that finished is saved on the server.
          {/if}
        </p>
      {:else}
        <h2>The scan failed</h2>
        <div class="note bad">{st.error ?? "Something went wrong on the server."}</div>
      {/if}
      {#if st.led_status}
        <div class="result"><LedStatus counts={st.counts} status={st.led_status} /></div>
      {/if}
      <div class="actions">
        {#if st.led_status}
          <button disabled={shown} onclick={showResult}>{shown ? "On the LEDs" : "Show on the LEDs"}</button>
        {/if}
        <button class={st.led_status ? "" : "primary"} onclick={again}>Scan again</button>
      </div>
      {#if st.led_status}
        <button class="primary wide" onclick={review}>Review the map</button>
      {/if}
    {/if}

    {#if error}<div class="note bad">{error}</div>{/if}
  </section>
</div>

<style>
  .scan { display: flex; flex-direction: column; height: 100dvh; }
  .viewport { position: relative; flex: 1 1 auto; min-height: 0; background: #000; overflow: hidden; }
  video { width: 100%; height: 100%; object-fit: contain; display: block; }

  .overlay { position: absolute; left: 0; right: 0; display: flex; align-items: center; gap: 8px; padding: 12px; pointer-events: none; }
  .overlay > * { pointer-events: auto; }
  .overlay.top { top: 0; padding-top: calc(12px + env(safe-area-inset-top)); }
  .overlay.bottom {
    bottom: 0; padding-bottom: 24px; /* clear the panel's rounded lip */ justify-content: space-between; color: rgba(255, 255, 255, 0.75);
    font-size: 12px; text-shadow: 0 1px 3px #000;
  }
  .round-btn {
    width: 44px; min-height: 44px; padding: 0; border-radius: 50%; display: grid; place-items: center;
    background: rgba(0, 0, 0, 0.5); border-color: rgba(255, 255, 255, 0.15); color: #fff;
  }
  .pill {
    display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 999px;
    background: rgba(0, 0, 0, 0.55); color: #fff; font-weight: 600; font-size: 14px;
    backdrop-filter: blur(6px);
  }
  .rec { width: 9px; height: 9px; border-radius: 50%; background: var(--faint); }
  .rec.live { background: #ff4d4d; animation: pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: 0.35; } }
  @media (prefers-reduced-motion: reduce) { .rec.live { animation: none; } }

  .countdown {
    position: absolute; inset: 0; display: grid; place-items: center; pointer-events: none;
    font-size: 120px; font-weight: 700; color: #fff; text-shadow: 0 4px 24px rgba(0, 0, 0, 0.6);
  }
  .cam-msg {
    position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
    justify-content: center; gap: 12px; padding: 24px; text-align: center;
  }

  .panel {
    flex: 0 0 auto; background: var(--surface); border-top: 1px solid var(--border);
    border-radius: var(--r2) var(--r2) 0 0; margin-top: -14px; position: relative;
    padding: 18px 16px calc(16px + env(safe-area-inset-bottom));
    max-height: 55dvh; overflow-y: auto;
  }
  .panel.compact { max-height: 35dvh; padding-top: 14px; }
  .compact h2 { font-size: 15px; margin-bottom: 6px; }
  .compact .hint { margin: 8px 0; font-size: 14px; }
  .compact .wide { margin-top: 10px; }
  .line {
    margin: 6px 0 0; font-size: 13px; color: var(--muted); display: -webkit-box;
    -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }
  .line.warn { color: var(--warn); }
  .line.open { display: block; }
  .row { display: flex; gap: 8px; margin-top: 10px; }
  .row button { flex: 1 1 0; }
  .step { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  .phase-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
  .hint { margin: 12px 0; font-size: 15px; }
  .wide { width: 100%; margin-top: 14px; }
  .result { margin-top: 12px; }
  .colours { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 8px; }
  .check { display: flex; gap: 10px; align-items: flex-start; margin: 10px 0 0; }
  .check input { margin-top: 3px; }
  .colours span {
    display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px;
    background: var(--surface-2); color: var(--muted);
  }
  .colours span.low { color: var(--bad); }
  .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  .dot.red { background: #ff3b30; }
  .dot.green { background: #34c759; }
  .dot.blue { background: #0a84ff; }
  .dot.white { background: #fff; box-shadow: 0 0 0 1px rgba(127, 127, 127, 0.5); }
  @media (min-width: 700px) {
    .panel { max-width: 560px; width: 100%; margin-left: auto; margin-right: auto; }
  }
</style>
