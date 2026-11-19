<script lang="ts">
  import { GitCompareArrows, Lightbulb, ScanLine } from "@lucide/svelte";
  import JobStatus from "../components/JobStatus.svelte";
  import Button from "../components/ui/Button.svelte";
  import Card from "../components/ui/Card.svelte";
  import Segmented from "../components/ui/Segmented.svelte";
  import StepHeader from "../components/ui/StepHeader.svelte";
  import { runEffect, selectLed, setViewMode, stopEffect } from "../lib/actions";
  import { STATUS_COLORS } from "../lib/colors";
  import { app, setStep } from "../lib/state.svelte";
  import { cm } from "../lib/util";
  import LedInspector from "./LedInspector.svelte";

  const map = $derived(app.map);
  const n = $derived(map?.status.length ?? 0);
  const counts = $derived(map?.counts ?? { ok: 0, interpolated: 0, failed: 0 });
  let filter = $state<"all" | "interpolated" | "failed">("all");
  const problems = $derived(map ? map.status.flatMap((s, i) => (s !== "ok" && (filter === "all" || s === filter) ? [i] : [])) : []);
  const LIMIT = 120;

  function toggleEffect(name: string) {
    if (app.engine.running === name) stopEffect();
    else runEffect(name);
  }
</script>

<StepHeader title="Map" description="How well each LED is placed. Check it on the tree, compare it with the truth, and fix problem LEDs." />

{#if !map}
  <Card>
    <p class="muted">No map yet: scan the tree first.</p>
    <Button variant="primary" icon={ScanLine} onclick={() => setStep("scan")}>Go to Scan</Button>
  </Card>
{:else}
  <Card title="Placement">
    <div class="stack" aria-hidden="true">
      {#each Object.entries(counts) as [s, c]}<i style="flex: {c}; background: {STATUS_COLORS[s]}"></i>{/each}
    </div>
    <div class="counts">
      <div><b class="mono ok">{counts.ok}</b><span>placed</span></div>
      <div><b class="mono interpolated">{counts.interpolated}</b><span>interpolated</span></div>
      <div><b class="mono failed">{counts.failed}</b><span>failed</span></div>
      <div><b class="mono">{n}</b><span>LEDs</span></div>
    </div>
    <p class="hint">{map.rounds ?? "?"} scan round{map.rounds === 1 ? "" : "s"}{map.created ? ` · ${new Date(map.created).toLocaleString()}` : ""}</p>
  </Card>

  <Card title="Check on the tree">
    <div class="buttons">
      <Button icon={Lightbulb} active={app.engine.running === "map-status"} disabled={app.scanning}
        title="Light every LED in its status colour" onclick={() => toggleEffect("map-status")}>Status colours</Button>
      <Button icon={ScanLine} active={app.engine.running === "map-verify"} disabled={app.scanning}
        title="A plane rising, then sweeping left to right, through the mapped positions" onclick={() => toggleEffect("map-verify")}>Verify sweep</Button>
    </div>
    <p class="hint">In the sweep, an LED lighting out of step with its neighbours is in the wrong place.</p>
  </Card>

  {#if app.compare}
    {@const cmp = app.compare}
    <Card title="Accuracy vs the true tree">
      {#snippet actions()}
        <Button size="sm" icon={GitCompareArrows} active={app.viewMode === "compare"} onclick={() => setViewMode("compare")}>Show</Button>
      {/snippet}
      <table>
        <thead><tr><th></th><th class="n">LEDs</th><th class="n">median</th><th class="n">95%</th></tr></thead>
        <tbody>
          {#each cmp.rows.filter((r) => r.count) as r}
            <tr class:all={r.status === "all"}>
              <td><i class="sw" style="background: {STATUS_COLORS[r.status] ?? 'transparent'}"></i>{r.status}</td>
              <td class="n mono">{r.count}</td>
              <td class="n mono">{cm(r.median * cmp.height_m)}</td>
              <td class="n mono">{cm(r.p95 * cmp.height_m)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <p class="hint">After the best alignment: rotated {cmp.rotation_deg.toFixed(0)}°, scale {cmp.scale.toFixed(3)}.</p>
    </Card>
  {/if}

  {#if app.selectedLed !== null}<LedInspector index={app.selectedLed} />{/if}

  <Card title="Problem LEDs">
    <Segmented size="sm" value={filter} onchange={(v) => (filter = v)} options={[
      { value: "all", label: `All ${counts.interpolated + counts.failed}` },
      { value: "interpolated", label: `Interpolated ${counts.interpolated}` },
      { value: "failed", label: `Failed ${counts.failed}` },
    ]} />
    {#if problems.length}
      <div class="chips">
        {#each problems.slice(0, LIMIT) as i (i)}
          <button class="chip" class:sel={app.selectedLed === i} style="--c: {STATUS_COLORS[map.status[i]]}"
            title="LED {i}: {map.status[i]}" onclick={() => selectLed(i)}>{i}</button>
        {/each}
        {#if problems.length > LIMIT}<span class="muted">+{problems.length - LIMIT} more</span>{/if}
      </div>
      <p class="hint">Click one (or any LED in the 3D view) to light it and inspect it.</p>
    {:else}
      <p class="hint">None. Every LED is placed.</p>
    {/if}
  </Card>
{/if}

<JobStatus kinds={["interpolate", "measure"]} />

<style>
  .stack { display: flex; height: 8px; border-radius: 4px; overflow: hidden; gap: 2px; }
  .counts { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--s2); }
  .counts div { display: flex; flex-direction: column; }
  .counts b { font-size: var(--t-xl); font-weight: 600; }
  .counts span { font-size: var(--t-xs); color: var(--muted); }
  .hint { margin: 0; font-size: var(--t-sm); color: var(--muted); }
  .buttons { display: flex; gap: var(--s2); flex-wrap: wrap; }
  table { font-size: var(--t-sm); }
  .n { text-align: right; }
  tr.all td { border-top: 1px solid var(--border); color: var(--muted); }
  .sw { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { font: var(--t-xs) var(--mono); padding: 2px 7px; border-radius: 10px; cursor: pointer;
    background: var(--surface-3); color: var(--c); border: 1px solid var(--border); }
  .chip:hover, .chip.sel { border-color: var(--c); }
  .chip.sel { background: var(--surface); }
</style>
