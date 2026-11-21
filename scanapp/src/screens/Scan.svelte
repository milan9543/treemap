<script lang="ts">
  // Step 2: film the LEDs while the server flashes their codes, round after round.
  //
  // The server runs the scan (countdown, then rounds of flashing, solving and showing the
  // result on the LEDs) and this page films for it: frames go up every 250 ms for as
  // long as the scan runs, and its state is polled once a second.
  import { onDestroy, onMount } from "svelte";
  import LedStatus from "../components/LedStatus.svelte";
  import { ApiError, type Api, type Phase, type ScanState } from "../lib/api";
  import { cameraName, openRearCamera, type Camera } from "../lib/camera";
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

  function hint(phase: Phase | null): string {
    const tree = app.shape === "tree";
    switch (phase) {
      case "flashing":
        return tree ? "Walk slowly round the tree, keeping all of it in view."
          : "Keep every LED in view and the phone steady.";
      case "solving":
        return "Keep the camera on the LEDs.";
      case "status":
        return tree ? "The tree shows this round: green found, yellow guessed, red missing. " +
            "Walk to where it's red: the next round starts in a moment."
          : "The LEDs show this round: green found, yellow guessed, red missing. Make sure " +
            "nothing hides the red ones: the next round starts in a moment.";
      default:
        return "The LEDs glow white: point the camera at them, with all of them in view.";
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
      const { id } = await api.scanStart({ shape: app.shape });
      st = null;
      phaseKey = "";
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

  async function finish() {
    await up.stop();
    await wake?.release().catch(() => {});
    wake = null;
    try {
      app.info = await api.info();
    } catch {
      /* shown on the next connect */
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

  <section class="panel">
    {#if view === "ready"}
      <div class="step">Step 2 of 2</div>
      <h2>Scan the {app.shape === "flat" ? "LEDs" : "tree"}</h2>
      <p class="muted small">
        {#if app.shape === "tree"}
          Stand where you can see the whole tree. Once it starts, the LEDs glow white for a
          few seconds, then flash their codes while you walk slowly round it. Each round ends
          with the tree showing what was found; it carries on until every LED is found.
        {:else}
          Hold the phone so every LED is in view, as square-on as you can. The LEDs glow white
          for a few seconds, then flash their codes; each round ends with them showing what
          was found.
        {/if}
      </p>
      {#if app.info?.map?.fits}
        <p class="small muted">This replaces the current map.</p>
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
      <p class="hint">{hint(st?.phase ?? null)}</p>
      {#if st?.phase === "status" && !st.identified}
        <div class="note warn">No LED was read this round. Is the camera on the LEDs, and are
          they flashing? Try standing closer.</div>
      {:else if st?.phase === "status"}
        <LedStatus counts={st.counts} status={st.led_status} />
      {/if}
      {#if st?.message && st.message !== "stopping…" && !(st.phase === "status" && !st.identified)}
        <div class="note info">{st.message}</div>
      {/if}
      {#if up.error}
        <div class="note bad">Frames aren't reaching the server: {up.error}</div>
      {:else if !cam}
        <div class="note warn">The camera is off, so nothing is being filmed.</div>
      {/if}
      <button class="wide {canFinish ? 'primary' : 'danger'}" disabled={stopping} onclick={stop}>
        {stopping ? "Stopping…" : canFinish ? "Finish here" : "Stop"}
      </button>
      {#if !canFinish && !stopping && st?.round}
        <p class="small muted after">Stopping keeps the rounds already finished.</p>
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
        <button class="primary" onclick={again}>Scan again</button>
      </div>
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
  .step { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  .phase-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
  .phase-head h2 { margin-bottom: 10px; }
  .hint { margin: 12px 0; font-size: 15px; }
  .wide { width: 100%; margin-top: 14px; }
  .after { margin: 8px 0 0; text-align: center; }
  .result { margin-top: 12px; }
  @media (min-width: 700px) {
    .panel { max-width: 560px; width: 100%; margin-left: auto; margin-right: auto; }
  }
</style>
