<script lang="ts">
  import * as controls from "./3d/controls";
  import Banners from "./components/Banners.svelte";
  import SettingsDrawer from "./components/SettingsDrawer.svelte";
  import TopBar from "./components/TopBar.svelte";
  import Viewport from "./components/Viewport.svelte";
  import { cycleViewMode } from "./lib/actions";
  import { app, save, setStep, STEPS, type Layer } from "./lib/state.svelte";
  import EffectsStep from "./steps/EffectsStep.svelte";
  import MapStep from "./steps/MapStep.svelte";
  import ScanStep from "./steps/ScanStep.svelte";
  import TreeStep from "./steps/TreeStep.svelte";

  const LAYER_KEYS: Record<string, Layer> = { o: "off", c: "cone", b: "branch", w: "wire" };

  function onkeydown(e: KeyboardEvent) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const target = e.target as HTMLElement;
    if (target.closest?.("input, select, textarea")) return; // typing in a form
    if (controls.walkKey(e, true)) return;
    const step = STEPS.find((s) => s.key === e.key);
    if (step && !app.walking && (step.id !== "tree" || app.sim)) setStep(step.id);
    else if (e.key === "[") { app.sidebar = !app.sidebar; save("sidebar", app.sidebar); }
    else if (e.key === "f") controls.setWalking(!app.walking);
    else if (e.key === "t") cycleViewMode();
    else if (e.key === "r") controls.resetView();
    else if (LAYER_KEYS[e.key] && !(app.walking && e.key === "w")) app.layers[LAYER_KEYS[e.key]] = !app.layers[LAYER_KEYS[e.key]];
  }
</script>

<svelte:window {onkeydown} />

<div class="app" class:walking={app.walking}>
  {#if !app.walking}
    <TopBar />
    <Banners />
  {/if}
  <div class="main">
    {#if !app.walking && app.sidebar}
      <aside class="sidebar">
        {#if app.step === "tree"}<TreeStep />
        {:else if app.step === "scan"}<ScanStep />
        {:else if app.step === "map"}<MapStep />
        {:else}<EffectsStep />{/if}
      </aside>
    {/if}
    <Viewport />
  </div>
</div>
<SettingsDrawer />

<style>
  .app { height: 100%; display: flex; flex-direction: column; }
  .main { flex: 1; min-height: 0; display: flex; position: relative; }
  .sidebar { width: var(--sidebar-w); flex: none; overflow-y: auto; background: var(--surface);
    border-right: 1px solid var(--border); padding: var(--s4); display: flex; flex-direction: column; gap: var(--s3); }
  @media (max-width: 760px) {
    .sidebar { position: absolute; inset: 0 auto 0 0; width: min(var(--sidebar-w), 92vw); z-index: 10; box-shadow: var(--shadow); }
  }
</style>
