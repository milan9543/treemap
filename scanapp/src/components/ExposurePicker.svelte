<script lang="ts">
  // The exposures the scan tried, as a strip from darker to brighter: each one's bar is
  // how many LEDs the server saw at it. The one that's set is highlighted; "auto" marks
  // the automatic pick. Tapping another sets it and counts its LEDs (see Scan.svelte).
  import { stepName, tooBright, type Step } from "../lib/exposure";

  let { steps, chosen, auto, trying, picking, ledCount, onpick }: {
    steps: Step[];
    chosen: number | null; // set on the camera
    auto: number | null; // picked automatically
    trying: number | null; // being set and counted
    picking: boolean; // the user may pick (else the search is running)
    ledCount: number;
    onpick: (i: number) => void;
  } = $props();

  let strip = $state<HTMLDivElement>();

  // Darker to brighter: exposure time × ISO.
  const order = $derived(steps.map((s, i) => ({ s, i }))
    .sort((a, b) => a.s.ms * (a.s.iso ?? 100) - b.s.ms * (b.s.iso ?? 100)));
  const top = $derived(Math.max(1, ...steps.filter((s) => !tooBright(s, ledCount)).map((s) => s.leds ?? 0)));
  const showIso = $derived(steps.some((s) => s.iso !== null && s.iso !== steps[0]?.iso));
  const sel = $derived(chosen === null ? null : steps[chosen]);

  const ms = (v: number) => (v < 1 ? `${v}` : `${Math.round(v * 10) / 10}`);

  // Keep the one being tried, else the chosen one, in view.
  $effect(() => {
    const i = trying ?? chosen;
    if (i === null || !strip) return;
    strip.querySelector<HTMLElement>(`[data-i="${i}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  });
</script>

<div class="picker">
  <div class="ends small"><span>Darker</span><span>Brighter</span></div>
  <div class="strip" bind:this={strip} role="radiogroup" aria-label="Exposure">
    {#each order as { s, i } (i)}
      {@const over = tooBright(s, ledCount)}
      <button role="radio" aria-checked={chosen === i} data-i={i}
              class:on={chosen === i} class:over class:untried={s.leds === null} class:busy={trying === i}
              disabled={!picking || trying !== null} onclick={() => onpick(i)}
              aria-label="{stepName(s)}: {s.leds === null ? 'not tried' : `${s.leds} LEDs`}{over ? ', too bright' : ''}">
        <span class="count num">{trying === i ? "…" : (s.leds ?? "–")}</span>
        <span class="bar"><span class="fill" style:height="{s.leds === null ? 0 : Math.min(100, (100 * s.leds) / top)}%"></span></span>
        <span class="ms num">{ms(s.ms)}<small>ms</small></span>
        {#if showIso}<span class="iso num">{s.iso === null ? "" : `ISO ${s.iso}`}</span>{/if}
        <span class="tag">{i === auto ? "auto" : ""}</span>
      </button>
    {/each}
  </div>

  {#if !picking}
    <p class="caption muted">Trying them from darker to brighter, counting the LEDs each one shows…</p>
  {:else if sel}
    <p class="caption">
      <b class="num">{stepName(sel)}</b>
      {#if sel.leds !== null}<span class="num"> · {sel.leds} LEDs seen</span>{/if}
      <br />
      <span class="muted">
        {#if tooBright(sel, ledCount)}
          <span class="warn">Too bright: it sees more than the LEDs (lit branches, the room or noise).</span>
        {:else if chosen === auto}
          Picked automatically: the darkest that sees nearly as many LEDs as any brighter one.
        {:else}
          Picked by you.
        {/if}
      </span>
    </p>
  {/if}
</div>

<style>
  .picker { margin: 4px 0 6px; }
  .ends { display: flex; justify-content: space-between; color: var(--faint); margin-bottom: 4px; }
  .ends span::before { content: "◂ "; }
  .ends span:last-child::before { content: ""; }
  .ends span:last-child::after { content: " ▸"; }

  .strip {
    display: flex; gap: 4px; overflow-x: auto; scroll-snap-type: x proximity; padding: 2px 2px 6px;
    scrollbar-width: none;
  }
  .strip::-webkit-scrollbar { display: none; }
  button {
    flex: 1 0 44px; min-height: 0; scroll-snap-align: center; display: flex; flex-direction: column;
    align-items: center; gap: 3px; padding: 6px 2px 4px; border-radius: var(--r1, 8px);
    background: var(--surface-2); border: 1px solid transparent; color: var(--muted); font: inherit;
  }
  button:disabled { opacity: 1; cursor: default; }
  button.on { border-color: var(--accent); background: var(--accent-bg); color: var(--text); }
  .count { font-size: 12px; font-weight: 600; color: var(--text); min-height: 16px; }
  .untried .count { color: var(--faint); }
  .bar { width: 14px; height: 44px; border-radius: 3px; background: var(--surface-3); display: flex; align-items: flex-end; overflow: hidden; }
  .fill { width: 100%; background: var(--faint); border-radius: 3px 3px 0 0; transition: height 0.25s; }
  .on .fill { background: var(--accent); }
  .over .fill { background: repeating-linear-gradient(45deg, var(--warn) 0 3px, transparent 3px 6px); }
  .over .count { color: var(--warn); }
  .busy .bar { animation: pulse 1s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: 0.4; } }
  @media (prefers-reduced-motion: reduce) { .busy .bar { animation: none; } }
  .ms { font-size: 12px; color: inherit; white-space: nowrap; }
  .ms small { font-size: 10px; margin-left: 1px; color: var(--faint); }
  .iso { font-size: 10px; color: var(--faint); white-space: nowrap; min-height: 13px; }
  .tag { font-size: 9px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent); min-height: 12px; }

  .caption { margin: 6px 0 0; font-size: 14px; line-height: 1.45; }
  .muted { color: var(--muted); font-size: 13px; }
  .warn { color: var(--warn); }
</style>
