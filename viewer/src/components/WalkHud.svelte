<script lang="ts">
  import { PHASES, phaseTotal, roundLabel } from "../lib/scan";
  import { app } from "../lib/state.svelte";
  import ProgressBar from "./ui/ProgressBar.svelte";

  const p = $derived(app.scanning ? app.job.progress : null);
  const total = $derived(p ? phaseTotal(p) : undefined);
  const phase = $derived(p ? PHASES[p.phase] : "");
</script>

<div class="top">
  {#if p}
    <div class="pill">
      <div class="line"><b>{roundLabel(p)}</b><span>{phase}</span>
        {#if p.remaining !== undefined}<span class="mono">{Math.ceil(p.remaining)} s</span>{/if}
      </div>
      {#if total && p.remaining !== undefined}
        <ProgressBar value={1 - p.remaining / total} tone={p.phase === "status" ? "warn" : "accent"} />
      {/if}
      <div class="line small">
        {#if p.phase === "status" && p.counts}
          <span class="ok">{p.counts.ok} ok</span><span class="interpolated">{p.counts.interpolated} interpolated</span>
          <span class="failed">{p.counts.failed} unknown</span>
        {:else if p.phase === "status" && p.message}
          <span class="warn">{p.message}</span>
        {:else if p.round === 0}
          <span>get the phone pointed at the tree</span>
        {:else}
          <span>{p.identified ?? 0} LEDs identified this round</span>
        {/if}
      </div>
    </div>
  {:else}
    <div class="pill"><div class="line"><b>Walk mode</b><span class="muted">start a scan in the Scan step to map the tree</span></div></div>
  {/if}
</div>

{#if app.locked}
  <div class="crosshair"></div>
  <div class="keys">
    <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> move · mouse looks · <kbd>Space</kbd>/<kbd>Shift</kbd> up/down ·
    <kbd>Esc</kbd> pause
  </div>
{/if}

<style>
  .top { position: absolute; top: var(--s3); left: 50%; transform: translateX(-50%); pointer-events: none; }
  .pill { min-width: 320px; padding: var(--s2) var(--s3); display: flex; flex-direction: column; gap: 6px;
    background: rgba(17, 21, 28, 0.9); border: 1px solid var(--border-strong); border-radius: var(--r2); box-shadow: var(--shadow); }
  .line { display: flex; gap: var(--s3); align-items: baseline; }
  .line .mono { margin-left: auto; color: var(--muted); }
  .small { font-size: var(--t-sm); color: var(--muted); }
  .crosshair { position: absolute; left: 50%; top: 50%; width: 6px; height: 6px; margin: -3px 0 0 -3px;
    border-radius: 50%; border: 1px solid rgba(255, 255, 255, 0.5); pointer-events: none; }
  .keys { position: absolute; left: 50%; bottom: var(--s3); transform: translateX(-50%); white-space: nowrap;
    padding: 6px var(--s3); font-size: var(--t-sm); color: var(--muted); pointer-events: none;
    background: rgba(17, 21, 28, 0.85); border: 1px solid var(--border); border-radius: var(--r2); }
</style>
