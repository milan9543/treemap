<script lang="ts">
  import { Plus, Sparkles, X } from "@lucide/svelte";
  import Alert from "../components/ui/Alert.svelte";
  import Button from "../components/ui/Button.svelte";
  import Card from "../components/ui/Card.svelte";
  import Field from "../components/ui/Field.svelte";
  import StepHeader from "../components/ui/StepHeader.svelte";
  import Toggle from "../components/ui/Toggle.svelte";
  import { generate } from "../lib/actions";
  import { app } from "../lib/state.svelte";
  import type { TreeSpec } from "../lib/types";

  type Row = { leds: number | null; length: number | null; start: string };
  let strips = $state<Row[]>([]);
  let height = $state<number | null>(null);
  let radius = $state<number | null>(null);
  let layout = $state("auto");
  let seed = $state<number | null>(null);
  let quirks = $state(true);
  let busy = $state(false);
  let result = $state<{ tone: "ok" | "warn" | "bad"; text: string } | null>(null);
  let filled = false;

  function fill(spec: TreeSpec) {
    strips = spec.strips.map((s) => ({ leds: s.leds, length: s.length, start: s.start || "auto" }));
    height = spec.height;
    radius = spec.radius;
    layout = spec.layout || "auto";
    quirks = spec.quirks !== false;
    seed = null; // blank = a new random tree each time
  }

  $effect(() => {
    if (filled) return;
    const spec = app.tree?.spec ?? app.config?.defaults;
    if (spec) { fill(spec); filled = true; }
  });

  const limits = $derived(app.config?.limits ?? { spacing: [0.01, 0.5], strips: [1, 8] });
  const total = $derived(strips.reduce((a, s) => a + (s.leds && s.leds > 0 ? s.leds : 0), 0));
  const rnd = $derived(app.config?.random);

  function spacing(s: Row): { text: string; bad: boolean } {
    if (!s.leds || s.leds < 1) return { text: "–", bad: true };
    if (s.length === null || s.length === undefined) return { text: "random", bad: false };
    const sp = s.length / s.leds;
    return { text: `${(sp * 100).toFixed(1)} cm`, bad: !(sp >= limits.spacing[0] && sp <= limits.spacing[1]) };
  }

  const blank = (v: number | null | undefined) => (v === undefined || v === null || Number.isNaN(v) ? null : v);

  async function run() {
    if (strips.some((s) => !Number.isInteger(s.leds) || (s.leds ?? 0) < 1)) {
      result = { tone: "bad", text: "Every strip needs a whole number of LEDs." };
      return;
    }
    busy = true;
    result = null;
    const reply = await generate({
      strips: strips.map((s) => ({ leds: s.leds, length: blank(s.length), start: s.start })),
      height: blank(height), radius: blank(radius), layout, quirks, seed: blank(seed),
    });
    busy = false;
    if (reply.ok) {
      const warn = (reply.warnings?.length ?? 0) > 0;
      result = { tone: warn ? "warn" : "ok", text: `Generated seed ${reply.seed}: ${reply.led_count} LEDs.` };
    } else {
      result = { tone: "bad", text: reply.error ?? "generation failed" };
    }
  }
</script>

<StepHeader title="Tree" description="The simulated tree: where its LEDs really are. Generate a new one to practise scanning on." />

{#if app.tree}
  {@const t = app.tree}
  <Card title="Current tree">
    <dl class="facts">
      <div><dt>Seed</dt><dd class="mono">{t.seed}</dd></div>
      <div><dt>LEDs</dt><dd class="mono">{t.led_count}</dd></div>
      <div><dt>Height</dt><dd class="mono">{t.height.toFixed(2)} m</dd></div>
      <div><dt>Radius</dt><dd class="mono">{t.radius.toFixed(2)} m</dd></div>
    </dl>
    <ul class="strands">
      {#each t.strands as s, i}
        <li><b>Strip {i + 1}</b> <span class="mono">LEDs {s.start}–{s.start + s.count - 1}</span>
          <span class="muted">{(s.spacing * 100).toFixed(1)} cm apart · {s.turns.toFixed(1)} turns · index 0 at the {s.index_from_top ? "top" : "bottom"}</span></li>
      {/each}
    </ul>
    {#each t.warnings ?? [] as w}<Alert tone="warn">{w}</Alert>{/each}
  </Card>
{/if}

<Card title="Generate a new tree">
  <table class="strips">
    <thead><tr><th></th><th>LEDs</th><th>Length m</th><th>Spacing</th><th title="Which end of the strip is LED index 0">Start</th><th></th></tr></thead>
    <tbody>
      {#each strips as s, i}
        {@const sp = spacing(s)}
        <tr>
          <td class="muted mono">{i + 1}</td>
          <td><input type="number" min="1" step="1" bind:value={s.leds} aria-label="LEDs on strip {i + 1}" /></td>
          <td><input type="number" min="0.1" step="0.1" placeholder="random" bind:value={s.length} aria-label="Length of strip {i + 1}" /></td>
          <td class="mono" class:bad={sp.bad}>{sp.text}</td>
          <td><select bind:value={s.start} aria-label="Index 0 of strip {i + 1}">
            <option value="auto">auto</option><option value="bottom">bottom</option><option value="top">top</option>
          </select></td>
          <td><Button variant="ghost" size="sm" icon={X} title="Remove this strip" disabled={strips.length <= 1}
            onclick={() => strips.splice(i, 1)} /></td>
        </tr>
      {/each}
    </tbody>
  </table>
  <div class="row">
    <Button size="sm" icon={Plus} disabled={strips.length >= limits.strips[1]}
      onclick={() => strips.push({ ...(strips.at(-1) ?? { leds: 200, length: null }), start: "auto" })}>Strip</Button>
    <span class="total mono">{total} LEDs</span>
  </div>
  <div class="grid">
    <Field label="Height (m)" hint="Blank = random"><input type="number" step="0.05" min="0.3" max="5" bind:value={height}
      placeholder={rnd ? `random ${rnd.height[0]}–${rnd.height[1]}` : "random"} /></Field>
    <Field label="Radius (m)" hint="Blank = random"><input type="number" step="0.05" min="0.1" max="2.5" bind:value={radius}
      placeholder={rnd ? `random ${rnd.radius[0]}–${rnd.radius[1]}` : "random"} /></Field>
    <Field label="Layout"><select bind:value={layout}>
      <option value="auto">auto</option><option value="interleaved">interleaved</option><option value="stacked">stacked</option>
    </select></Field>
    <Field label="Seed"><input type="number" min="0" step="1" bind:value={seed} placeholder="random" /></Field>
  </div>
  <Toggle bind:checked={quirks} title="Let 'auto' settings pick quirks at random: strips indexed from the top, stacked layout">
    Random wiring quirks for "auto"
  </Toggle>
  <div class="row">
    <Button variant="primary" icon={Sparkles} disabled={busy || app.jobActive} onclick={run}>{busy ? "Generating…" : "Generate"}</Button>
    <Button variant="ghost" title="Reset the form to the sim section of config.yaml"
      onclick={() => { if (app.config) fill(app.config.defaults); result = null; }}>Config defaults</Button>
  </div>
  {#if result}<Alert tone={result.tone}>{result.text}</Alert>{/if}
  {#if app.jobActive}<p class="muted small">Wait for the running {app.job.kind} to finish before generating.</p>{/if}
</Card>

<style>
  .facts { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--s2); margin: 0; }
  .facts div { display: flex; flex-direction: column; }
  dt { font-size: var(--t-xs); color: var(--muted); }
  dd { margin: 0; font-size: var(--t-md); }
  .strands { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 3px; font-size: var(--t-sm); }
  .strands li { display: grid; grid-template-columns: auto 1fr; column-gap: var(--s2); }
  .strands li .muted { grid-column: 1 / -1; font-size: var(--t-xs); }
  .strips { table-layout: fixed; }
  .strips th, .strips td { padding: 2px; }
  .strips th:nth-child(1) { width: 14px; }
  .strips th:nth-child(2) { width: 60px; }
  .strips th:nth-child(3) { width: 66px; }
  .strips th:nth-child(5) { width: 80px; }
  .strips th:nth-child(6) { width: 28px; }
  .strips td:nth-child(4) { font-size: var(--t-xs); color: var(--muted); white-space: nowrap; overflow: hidden; }
  .strips input, .strips select { padding: 4px 5px; }
  .strips td.bad { color: var(--bad); }
  .row { display: flex; align-items: center; justify-content: space-between; gap: var(--s2); }
  .total { font-size: var(--t-sm); color: var(--muted); }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s2) var(--s3); }
  .small { font-size: var(--t-sm); margin: 0; }
</style>
