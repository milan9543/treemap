<script lang="ts">
  import { Footprints, Layers, RotateCcw } from "@lucide/svelte";
  import * as controls from "../3d/controls";
  import { modeAvailable } from "../3d/scene";
  import { setViewMode } from "../lib/actions";
  import { app, type Layer, type ViewMode } from "../lib/state.svelte";
  import Button from "./ui/Button.svelte";
  import Popover from "./ui/Popover.svelte";
  import Segmented from "./ui/Segmented.svelte";
  import Toggle from "./ui/Toggle.svelte";

  // re-evaluated when the data changes (modeAvailable reads the scene's positions)
  const modes = $derived.by(() => {
    void app.tree; void app.map; void app.compare;
    const all: { value: ViewMode; label: string; title: string }[] = [
      { value: "truth", label: "Truth", title: "Where the LEDs really are (t)" },
      { value: "scan", label: "Scanned", title: "Where the scan put them (t)" },
      { value: "compare", label: "Compare", title: "A line from each true position to the scanned one, coloured by error (t)" },
    ];
    return all
      .filter((m) => app.sim || m.value === "scan")
      .map((m) => ({ ...m, disabled: !modeAvailable(m.value) }));
  });

  const LAYERS: { id: Layer; label: string; key: string }[] = [
    { id: "off", label: "Unlit LEDs", key: "o" },
    { id: "cone", label: "Cone and trunk", key: "c" },
    { id: "branch", label: "Branches", key: "b" },
    { id: "wire", label: "Wire path", key: "w" },
  ];
</script>

<div class="toolbar">
  {#if modes.length > 1}
    <Segmented options={modes} value={app.viewMode} onchange={setViewMode} />
  {/if}
  <Popover up>
    {#snippet trigger(toggle, open)}
      <Button icon={Layers} active={open} onclick={toggle} title="Layers">Layers</Button>
    {/snippet}
    {#each LAYERS as l (l.id)}
      <div class="layer"><Toggle bind:checked={app.layers[l.id]}>{l.label}</Toggle><kbd>{l.key}</kbd></div>
    {/each}
  </Popover>
  <Button icon={RotateCcw} title="Reset the view (r)" onclick={controls.resetView}>Reset</Button>
  <Button icon={Footprints} title="Walk round the tree in first person (f)" onclick={() => controls.setWalking(true)}>Walk</Button>
</div>

<style>
  .toolbar { position: absolute; left: var(--s3); bottom: var(--s3); display: flex; gap: var(--s2); flex-wrap: wrap;
    align-items: center; padding: var(--s1); background: rgba(17, 21, 28, 0.88); border: 1px solid var(--border);
    border-radius: var(--r2); backdrop-filter: blur(6px); }
  .layer { display: flex; align-items: center; justify-content: space-between; gap: var(--s4); padding: 4px 6px; }
</style>
