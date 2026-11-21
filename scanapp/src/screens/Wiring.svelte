<script lang="ts">
  import { onDestroy } from "svelte";
  import TopBar from "../components/TopBar.svelte";
  import type { Api } from "../lib/api";
  import { app } from "../lib/state.svelte";

  let { api }: { api: Api } = $props();
  const n = app.info?.led_count ?? 0;

  // The chase takes about 12 s, however many LEDs there are.
  const speed = Math.max(10, Math.round(n / 12));
  let chase = $state<{ total: number; left: number } | null>(null);
  let answer = $state<"yes" | "no" | null>(null);
  let index = $state(0);
  let lit = $state(false);
  let error = $state<string | null>(null);
  let timer: ReturnType<typeof setInterval> | undefined;

  async function run(cmd: Record<string, unknown>) {
    error = null;
    try {
      return await api.leds(cmd);
    } catch (e) {
      error = (e as Error).message;
      return null;
    }
  }

  async function runChase() {
    clearInterval(timer);
    lit = false;
    answer = null;
    const r = await run({ mode: "chase", color: "white", width: 3, speed });
    if (!r?.seconds) return;
    const end = performance.now() + r.seconds * 1000;
    chase = { total: r.seconds, left: r.seconds };
    timer = setInterval(() => {
      const left = Math.max(0, (end - performance.now()) / 1000);
      chase = { total: r.seconds!, left };
      if (left <= 0) clearInterval(timer);
    }, 200);
  }

  async function light(i: number) {
    index = Math.min(Math.max(0, Math.round(i) || 0), n - 1);
    clearInterval(timer);
    chase = null;
    lit = (await run({ mode: "led", index, color: "white" })) !== null;
  }

  async function off() {
    clearInterval(timer);
    chase = null;
    lit = false;
    await run({ mode: "off" });
  }

  onDestroy(() => {
    clearInterval(timer);
    void api.leds({ mode: "off" }).catch(() => {});
  });

  const running = $derived(chase !== null && chase.left > 0);
</script>

<main class="page">
  <TopBar title="Check the wiring" step="Step 1 of 2" back="connect" />
  <p class="muted">The map numbers the LEDs in the order the data runs through them. Check that
    order before scanning.</p>

  <section class="card">
    <h2>Run a light along the LEDs</h2>
    <p class="small muted">A white light runs from the first LED to the last, {speed} LEDs a second.
      Watch where it goes.</p>
    {#if chase}
      <div class="bar" aria-hidden="true">
        <div style:width="{100 * (1 - chase.left / chase.total)}%"></div>
      </div>
      <p class="small muted num status">{running ? `${Math.ceil(chase.left)} s left` : "Done."}</p>
    {/if}
    <button class={chase ? "wide" : "primary wide"} onclick={runChase}>
      {chase ? "Run it again" : "Run the light"}
    </button>

    {#if chase && !running}
      <div class="question">
        <p><strong>Did it run from the start of the first strip to the end of the last,
          without jumping back?</strong></p>
        <div class="actions">
          <button aria-pressed={answer === "no"} onclick={() => (answer = "no")}>No</button>
          <button class="primary" onclick={() => { answer = "yes"; app.screen = "scan"; }}>
            Yes, scan</button>
        </div>
        {#if answer === "no"}
          <div class="note warn">
            The order comes from <span class="mono">controllers</span> in the server's config.
            <ul>
              <li>Several controllers: list them in the order the strips run.</li>
              <li>A strip runs the wrong way: give its controller <span class="mono">reverse: true</span>.</li>
              <li>The light stops early or skips a strip: check that controller's LED count in WLED.</li>
            </ul>
            Restart <span class="mono">treemap serve</span> after a change, then run the light again.
          </div>
        {/if}
      </div>
    {/if}
  </section>

  <section class="card">
    <h2>Light one LED</h2>
    <p class="small muted">To find a particular LED, say the end of a strip. Numbers start at 0.</p>
    <div class="stepper">
      <button aria-label="Previous LED" disabled={index <= 0} onclick={() => light(index - 1)}>−</button>
      <input type="number" inputmode="numeric" min="0" max={n - 1} aria-label="LED number"
             value={index} onchange={(e) => light(Number(e.currentTarget.value))} />
      <button aria-label="Next LED" disabled={index >= n - 1} onclick={() => light(index + 1)}>+</button>
    </div>
    <div class="actions">
      <button onclick={off}>All off</button>
      <button class={lit ? "" : "primary"} onclick={() => light(index)}>{lit ? `LED ${index} is lit` : "Light it"}</button>
    </div>
    <p class="small muted ends num">First LED 0, last LED {n - 1}.</p>
  </section>

  {#if error}<div class="note bad">{error}</div>{/if}

  <button class="link" onclick={() => (app.screen = "scan")}>Skip to the scan</button>
</main>

<style>
  .wide { width: 100%; margin-top: 4px; }
  .status { margin: 6px 0 10px; }
  .question { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border); }
  .question p { margin: 0; }
  .stepper { display: grid; grid-template-columns: 56px 1fr 56px; gap: 8px; }
  .stepper button { font-size: 22px; padding: 0; }
  .stepper input { text-align: center; font-variant-numeric: tabular-nums; }
  .ends { margin: 10px 0 0; }
</style>
