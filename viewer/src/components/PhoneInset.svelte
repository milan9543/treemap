<script lang="ts">
  // What the virtual phone films, with the scan's detections drawn on top.
  import { onMount } from "svelte";
  import { PHONE_H, PHONE_W, phoneCanvas } from "../3d/phone";
  import { app } from "../lib/state.svelte";

  let screen: HTMLDivElement;
  let overlay: HTMLCanvasElement;

  onMount(() => {
    screen.prepend(phoneCanvas);
    let raf = requestAnimationFrame(function draw() {
      paint();
      raf = requestAnimationFrame(draw);
    });
    return () => cancelAnimationFrame(raf);
  });

  function paint() {
    const ctx = overlay.getContext("2d")!;
    ctx.clearRect(0, 0, PHONE_W, PHONE_H);
    const d = app.detections;
    if (!d || !d.size[0] || performance.now() - app.detectionsAt > 1500) return;
    const sx = PHONE_W / d.size[0], sy = PHONE_H / d.size[1];
    ctx.lineWidth = 1.5;
    ctx.font = "12px ui-monospace, Menlo, monospace";
    for (const [u, v, led] of d.blobs) {
      const x = u * sx, y = v * sy;
      ctx.strokeStyle = led >= 0 ? "rgba(111, 211, 165, 0.95)" : "rgba(160, 170, 185, 0.5)";
      ctx.beginPath();
      ctx.arc(x, y, led >= 0 ? 6 : 4, 0, Math.PI * 2);
      ctx.stroke();
      if (led >= 0 && led % 5 === 0) {
        ctx.fillStyle = "rgba(225, 245, 235, 0.95)";
        ctx.fillText(String(led), x + 7, y - 5);
      }
    }
  }

  const streaming = $derived(app.scanners > 0);
  const identified = $derived(app.detections?.blobs.filter((b) => b[2] >= 0).length ?? 0);
</script>

<figure class="phone">
  <div class="screen" bind:this={screen}>
    <canvas bind:this={overlay} width={PHONE_W} height={PHONE_H}></canvas>
  </div>
  <figcaption>
    {#if streaming}
      <span><span class="rec">●</span> Phone · sending {app.phoneFps} fps</span>
      <span>{identified} identified in view</span>
    {:else}
      <span>Phone preview</span><span class="muted">starts sending when a scan runs</span>
    {/if}
  </figcaption>
</figure>

<style>
  .phone { position: absolute; right: var(--s3); bottom: var(--s3); margin: 0; width: 336px; padding: var(--s2);
    background: #000; border: 1px solid var(--border-strong); border-radius: 14px; box-shadow: var(--shadow); }
  .screen { position: relative; width: 320px; height: 240px; border-radius: var(--r1); overflow: hidden; background: #050607; }
  .screen :global(canvas) { position: absolute; inset: 0; width: 100%; height: 100%; }
  figcaption { display: flex; justify-content: space-between; gap: var(--s2); margin-top: 6px;
    font: var(--t-xs) var(--mono); color: var(--muted); }
  .rec { color: var(--bad); }
  @media (max-width: 760px) { .phone { width: 216px; } .screen { width: 200px; height: 150px; } }
</style>
