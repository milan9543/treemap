<script lang="ts">
  // The scan's result at a glance: how many LEDs were found, guessed and missed, and a
  // strip with one column per LED in wiring order, coloured as the LEDs show it.
  import type { Counts } from "../lib/api";

  // compact: the counts only, for the small panel while scanning
  let { counts, status, compact = false }: { counts: Counts | null; status?: string; compact?: boolean } = $props();
  let canvas = $state<HTMLCanvasElement>();

  const COLOURS: Record<string, string> = { o: "#4cc777", i: "#f0be5a", f: "#ef6f6f" };

  $effect(() => {
    if (!canvas || !status) return;
    canvas.width = status.length;
    canvas.height = 1;
    const ctx = canvas.getContext("2d")!;
    for (let i = 0; i < status.length; i++) {
      ctx.fillStyle = COLOURS[status[i]] ?? COLOURS.f;
      ctx.fillRect(i, 0, 1, 1);
    }
  });
</script>

{#if counts}
  <div class="counts num">
    <span><i class="dot ok"></i><b>{counts.ok}</b> found</span>
    <span><i class="dot interp"></i><b>{counts.interpolated}</b> guessed</span>
    <span><i class="dot failed"></i><b>{counts.failed}</b> missing</span>
  </div>
{/if}
{#if status && !compact}
  <canvas bind:this={canvas} class="strip" aria-label="Each LED's status, first to last"></canvas>
  <div class="ends small muted num"><span>0</span><span>{status.length - 1}</span></div>
{/if}

<style>
  .counts { display: flex; gap: 14px; flex-wrap: wrap; font-size: 14px; }
  .counts b { font-weight: 650; }
  .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; vertical-align: 0; }
  .ok { background: var(--ok); }
  .interp { background: var(--warn); }
  .failed { background: var(--bad); }
  .strip {
    display: block; width: 100%; height: 14px; margin-top: 10px; border-radius: 3px;
    image-rendering: pixelated; background: var(--surface-3);
  }
  .ends { display: flex; justify-content: space-between; margin-top: 2px; font-size: 11px; }
</style>
