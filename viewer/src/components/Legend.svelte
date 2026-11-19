<script lang="ts">
  import { app } from "../lib/state.svelte";
  import { STATUS_COLORS } from "../lib/colors";

  // only while the tree is actually lit in status colours
  const statusShown = $derived(
    (!app.scanning && (app.engine.running === "map-status" || app.engine.running === "map-verify")) ||
    (app.scanning && app.job.progress?.phase === "status"));
</script>

{#if app.viewMode === "compare" && app.compare}
  <div class="legend">
    <div class="title">Error: true → scanned position</div>
    <div class="scale"><span>0</span><i></i><span>5+ cm</span></div>
  </div>
{:else if statusShown && app.map}
  <div class="legend">
    <div class="title">Status colours</div>
    {#each Object.entries(STATUS_COLORS) as [s, c]}
      <div class="row"><i class="sw" style="background: {c}"></i>{s === "failed" ? "failed / unknown" : s}</div>
    {/each}
  </div>
{/if}

<style>
  .legend { position: absolute; top: var(--s3); right: var(--s3); padding: var(--s2) var(--s3);
    background: rgba(17, 21, 28, 0.88); border: 1px solid var(--border); border-radius: var(--r2);
    font-size: var(--t-sm); display: flex; flex-direction: column; gap: 4px; backdrop-filter: blur(6px); }
  .title { color: var(--muted); font-size: var(--t-xs); }
  .scale { display: flex; align-items: center; gap: 6px; font: var(--t-xs) var(--mono); color: var(--muted); }
  .scale i { width: 110px; height: 8px; border-radius: 4px;
    background: linear-gradient(90deg, hsl(119, 85%, 50%), hsl(60, 85%, 50%), hsl(0, 85%, 50%)); }
  .row { display: flex; align-items: center; gap: 6px; }
  .sw { width: 9px; height: 9px; border-radius: 50%; }
</style>
