<script lang="ts">
  import { Square, Sun } from "@lucide/svelte";
  import Alert from "../components/ui/Alert.svelte";
  import Button from "../components/ui/Button.svelte";
  import Card from "../components/ui/Card.svelte";
  import Segmented from "../components/ui/Segmented.svelte";
  import StepHeader from "../components/ui/StepHeader.svelte";
  import { runEffect, setBrightness, setEffectMap, stopEffect } from "../lib/actions";
  import type { MapChoice } from "../lib/types";
  import { app } from "../lib/state.svelte";
  import EffectParams from "./EffectParams.svelte";

  const effects = $derived(app.effects?.effects ?? []);
  // The Mapping effects live in the Map step; the single-LED one is how LEDs get selected.
  const groups = $derived([...new Set(effects.map((e) => e.group))].filter((g) => g !== "Mapping"));
  const running = $derived(effects.find((e) => e.name === app.engine.running) ?? null);
  let brightness = $state<number | null>(null); // while dragging
  const shownBrightness = $derived(brightness ?? Math.round(app.engine.brightness * 100));
  const MAP_LABELS: Record<MapChoice, { label: string; title: string }> = {
    scanned: { label: "Scanned map", title: "Where the scan placed each LED: what the real tree will use" },
    truth: { label: "True tree", title: "The simulated tree's real positions, to compare against" },
  };
  const mapOptions = $derived((app.engine.maps ?? []).map((m) => ({ value: m, ...MAP_LABELS[m] })));
</script>

<StepHeader title="Effects" description="Light shows that use the mapped positions. Pick one, then tune it." />

{#if !app.effects?.available}
  <Alert tone="warn">Effects aren't available from this server.</Alert>
{:else}
  <Card title="Now playing">
    {#snippet actions()}
      {#if running}<Button size="sm" variant="danger" icon={Square} onclick={stopEffect}>Stop</Button>{/if}
    {/snippet}
    {#if running}
      <div class="now"><b>{running.label}</b><span class="muted">{running.description}</span></div>
      {#if running.params.length}<EffectParams fx={running} />{/if}
    {:else if app.scanning}
      <p class="muted">The scan is using the LEDs. Effects can run once it's stopped.</p>
    {:else}
      <p class="muted">Nothing. Pick an effect below.</p>
    {/if}
    <label class="bright">
      <Sun size={15} />
      <input type="range" min="0" max="100" step="1" value={shownBrightness} aria-label="Brightness"
        oninput={(e) => { brightness = Number(e.currentTarget.value); setBrightness(brightness / 100); }}
        onchange={() => (brightness = null)} />
      <output class="mono">{shownBrightness}%</output>
    </label>
    {#if app.effectError}<Alert tone="bad">{app.effectError}</Alert>{/if}
  </Card>

  {#each groups as g}
    <Card title={g}>
      {#snippet actions()}
        {#if g === "3D" && mapOptions.length > 1 && app.engine.map}
          <Segmented size="sm" value={app.engine.map} onchange={setEffectMap} options={mapOptions} />
        {/if}
      {/snippet}
      <div class="grid">
        {#each effects.filter((e) => e.group === g) as e (e.name)}
          <button class="fx" class:on={app.engine.running === e.name} title={e.description} disabled={app.scanning}
            onclick={() => runEffect(e.name)}>
            <b>{e.label}</b>
            <span>{e.description}</span>
          </button>
        {/each}
      </div>
    </Card>
  {/each}
{/if}

<style>
  .now { display: flex; flex-direction: column; gap: 2px; font-size: var(--t-sm); }
  .now b { font-size: var(--t-lg); }
  p { margin: 0; font-size: var(--t-sm); }
  .bright { display: grid; grid-template-columns: 20px 1fr 44px; align-items: center; gap: var(--s2); color: var(--muted); }
  .bright output { text-align: right; font-size: var(--t-xs); color: var(--text); }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s2); }
  .fx { text-align: left; display: flex; flex-direction: column; gap: 2px; padding: var(--s2) var(--s3); cursor: pointer;
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--r1); color: var(--text); }
  .fx span { font-size: var(--t-xs); color: var(--muted); display: -webkit-box; -webkit-line-clamp: 2;
    line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .fx:hover:not(:disabled) { border-color: var(--border-strong); background: var(--surface-3); }
  .fx.on { border-color: var(--accent-border); background: var(--accent-bg); }
  .fx.on b { color: var(--accent); }
  .fx:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
