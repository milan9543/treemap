<script lang="ts">
  import { Crosshair, X } from "@lucide/svelte";
  import Button from "../components/ui/Button.svelte";
  import Card from "../components/ui/Card.svelte";
  import { selectLed, startJob } from "../lib/actions";
  import { STATUS_COLORS } from "../lib/colors";
  import { app } from "../lib/state.svelte";

  let { index }: { index: number } = $props();

  const map = $derived(app.map);
  const status = $derived(map?.status[index] ?? null);
  const strip = $derived(app.tree?.strands.findIndex((s) => index >= s.start && index < s.start + s.count) ?? -1);
  const err = $derived(app.compare?.errors_m[index]);
  const forced = $derived((map?.forced_interpolate ?? []).includes(index));
  const outlier = $derived((map?.outliers ?? []).includes(index));
  const views = $derived(map?.views?.[index]);
  const n = $derived(map?.status.length ?? app.tree?.led_count ?? 0);
  const near = $derived([-3, -2, -1, 1, 2, 3].map((d) => index + d).filter((j) => j >= 0 && j < n));
</script>

<Card title="LED {index}">
  {#snippet actions()}
    <Button variant="ghost" size="sm" icon={Crosshair} title="Light it blue again" onclick={() => selectLed(index)} />
    <Button variant="ghost" size="sm" icon={X} title="Close" onclick={() => (app.selectedLed = null)} />
  {/snippet}
  <dl class="facts">
    <div><dt>Status</dt><dd style="color: {status ? STATUS_COLORS[status] : 'inherit'}">{status ?? "not mapped"}</dd></div>
    {#if strip >= 0}<div><dt>Strip</dt><dd class="mono">{strip + 1}</dd></div>{/if}
    {#if views !== undefined}<div><dt>Seen in</dt><dd class="mono">{views} views</dd></div>{/if}
    {#if err !== undefined}<div><dt>Error</dt><dd class="mono">{err === null ? "–" : `${(err * 100).toFixed(1)} cm`}</dd></div>{/if}
  </dl>
  {#if outlier}<p class="note">Dropped as an outlier: too far from its neighbours on the strip.</p>{/if}
  {#if forced}<p class="note">Interpolated on request: its observations are ignored.</p>{/if}
  <div class="near">
    <span class="muted">Neighbours</span>
    {#each near as j}
      <button class="chip" style="--c: {map ? STATUS_COLORS[map.status[j]] : 'var(--muted)'}" title="LED {j}: {map?.status[j] ?? ''}"
        onclick={() => selectLed(j)}>{j}</button>
    {/each}
  </div>
  {#if map && app.jobsAvailable}
    <div class="buttons">
      {#if forced}
        <Button size="sm" disabled={app.jobActive} title="Use its observations again, then rebuild the map"
          onclick={() => startJob("measure", { index })}>Measure again</Button>
      {:else}
        <Button size="sm" disabled={app.jobActive} title="Ignore its observations from now on and fill it in from its neighbours"
          onclick={() => startJob("interpolate", { index })}>Interpolate</Button>
      {/if}
    </div>
    <p class="note">To measure it better, scan again and film that part of the tree.</p>
  {/if}
</Card>

<style>
  .facts { display: flex; gap: var(--s4); flex-wrap: wrap; margin: 0; }
  .facts div { display: flex; flex-direction: column; }
  dt { font-size: var(--t-xs); color: var(--muted); }
  dd { margin: 0; }
  .note { margin: 0; font-size: var(--t-sm); color: var(--muted); }
  .near { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; font-size: var(--t-sm); }
  .near .muted { margin-right: 4px; }
  .chip { font: var(--t-xs) var(--mono); padding: 1px 6px; border-radius: 10px; cursor: pointer;
    background: var(--surface-3); color: var(--c); border: 1px solid var(--border); }
  .chip:hover { border-color: var(--c); }
  .buttons { display: flex; gap: var(--s2); }
</style>
