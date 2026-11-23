<script lang="ts">
  // How smoothly the server sends frames (the engine's last 2 s), and what that says about
  // stutter on the LEDs. The server only sees its own side: frames that leave it evenly
  // and still reach the LEDs in fits and starts are held up on the Wi-Fi or the controller.
  import type { Timing } from "./api";

  let { t, sending }: { t: Timing; sending: boolean } = $props();

  const period = $derived(1000 / t.fps_target);
  // Paused now and then although the frame rate holds: the computer held the engine up.
  const jerky = $derived(!!t.gap_ms && t.gap_ms.max > 2 * period);
  const verdict = $derived.by(() => {
    if (!t.render_ms || !t.send_ms || !t.gap_ms) return null;
    if (t.slow) {
      const r = t.render_ms.median, s = t.send_ms.median;
      return r + s > 0.8 * period
        ? `The server can't keep up: ${r > s ? "rendering" : "sending"} a frame takes longer than the ${period.toFixed(0)} ms it has.`
        : "The server can't keep up: frames start late. Is the computer busy?";
    }
    if (jerky) return `The server paused for up to ${t.gap_ms.max.toFixed(0)} ms between frames: the computer is busy or putting the server to sleep for a moment.`;
    return null;
  });
  const fmt = (ms: number) => (ms < 10 ? ms.toFixed(1) : ms.toFixed(0));
</script>

{#if t.fps !== null && t.render_ms && t.send_ms && t.gap_ms}
  <div class="timing" class:warn={t.slow || jerky}
       title="Measured on the server over the last 2 s: frames per second sent, the time between frames, and the time to render and send one (median, worst in brackets).">
    <div class="nums mono">
      <span>{t.fps.toFixed(1)}/{t.fps_target} fps</span>
      <span>every {fmt(t.gap_ms.median)} ms (max {fmt(t.gap_ms.max)})</span>
      <span>render {fmt(t.render_ms.median)} (max {fmt(t.render_ms.max)})</span>
      <span>send {fmt(t.send_ms.median)} (max {fmt(t.send_ms.max)})</span>
      <span>{t.late} late</span>
    </div>
    {#if verdict}
      <p>{verdict}</p>
    {:else if sending}
      <p class="muted">Steady on the server. If the LEDs still speed up and slow down, the frames
        are held up on the Wi-Fi or in the controller.</p>
    {/if}
  </div>
{/if}

<style>
  .timing { display: flex; flex-direction: column; gap: 2px; font-size: var(--t-xs); }
  .nums { display: flex; flex-wrap: wrap; gap: 2px var(--s3); color: var(--muted); }
  .warn .nums, .warn p { color: var(--warn); }
  p { margin: 0; }
</style>
