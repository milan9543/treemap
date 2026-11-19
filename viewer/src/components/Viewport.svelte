<script lang="ts">
  // The 3D view and everything drawn over it.
  import { onMount } from "svelte";
  import * as controls from "../3d/controls";
  import { phoneActive, tick as phoneTick } from "../3d/phone";
  import * as scene from "../3d/scene";
  import { selectLed } from "../lib/actions";
  import { app, save, setStep } from "../lib/state.svelte";
  import Legend from "./Legend.svelte";
  import PauseOverlay from "./PauseOverlay.svelte";
  import PhoneInset from "./PhoneInset.svelte";
  import Button from "./ui/Button.svelte";
  import ViewToolbar from "./ViewToolbar.svelte";
  import WalkHud from "./WalkHud.svelte";

  let host: HTMLDivElement;
  let hover: PointerEvent | null = null;
  let downAt: [number, number] | null = null;
  let showPhone = $state(false);

  // keep the 3D layers in step with the toggles
  $effect(() => {
    for (const [name, on] of Object.entries(app.layers)) scene.setToggle(name as "off", on);
    save("layers", { ...app.layers });
  });

  onMount(() => {
    const canvas = scene.renderer.domElement;
    host.prepend(canvas);
    const ro = new ResizeObserver(([e]) => scene.resize(e.contentRect.width, e.contentRect.height));
    ro.observe(host);

    canvas.addEventListener("pointermove", (e) => { hover = e; });
    canvas.addEventListener("pointerleave", () => { hover = null; app.hover = null; });
    canvas.addEventListener("pointerdown", (e) => { downAt = [e.clientX, e.clientY]; });
    canvas.addEventListener("pointerup", (e) => {
      if (app.walking || !downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 4) return;
      const i = scene.pickLed(e.clientX, e.clientY);
      if (i !== null) selectLed(i);
    });

    scene.renderer.setAnimationLoop((now) => {
      controls.update();
      const i = hover && !app.walking ? scene.pickLed(hover.clientX, hover.clientY) : null;
      app.hover = i === null || !hover ? null : { x: hover.clientX, y: hover.clientY, text: scene.describeLed(i) };
      scene.renderer.render(scene.scene, scene.camera);
      phoneTick(now);
      const p = phoneActive();
      if (p !== showPhone) showPhone = p;
    });
    return () => {
      ro.disconnect();
      scene.renderer.setAnimationLoop(null);
    };
  });
</script>

<div class="viewport" bind:this={host}>
  {#if app.loaded && !app.tree && !app.map}
    <div class="empty">
      <h2>No tree yet</h2>
      {#if app.sim}
        <p>Set up the strips and size of a simulated tree, then generate it.</p>
        <Button variant="primary" onclick={() => setStep("tree")}>Set up a tree</Button>
      {:else}
        <p>Scan the tree to see where its LEDs are.</p>
        <Button variant="primary" onclick={() => setStep("scan")}>Go to Scan</Button>
      {/if}
    </div>
  {/if}

  {#if app.walking}
    <WalkHud />
    {#if !app.locked}<PauseOverlay />{/if}
  {:else}
    <ViewToolbar />
  {/if}
  <Legend />
  {#if showPhone}<PhoneInset />{/if}
</div>

{#if app.hover}
  {@const flip = app.hover.x > window.innerWidth - 380}
  <div class="tip mono" style="left: {app.hover.x + (flip ? -14 : 14)}px; top: {app.hover.y + 14}px"
    class:flip>{app.hover.text}</div>
{/if}

<style>
  .viewport { position: relative; flex: 1; min-width: 0; min-height: 0; overflow: hidden; background: var(--bg); }
  .viewport :global(canvas) { position: absolute; inset: 0; }
  .empty { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
    justify-content: center; gap: var(--s2); text-align: center; padding: var(--s4); }
  .empty h2 { margin: 0; font-size: var(--t-xl); }
  .empty p { margin: 0 0 var(--s2); color: var(--muted); }
  .tip { position: fixed; z-index: 30; pointer-events: none; background: var(--surface); border: 1px solid var(--border-strong);
    border-radius: var(--r1); padding: 3px 8px; font-size: var(--t-sm); white-space: nowrap; box-shadow: var(--shadow); }
  .tip.flip { transform: translateX(-100%); }
</style>
