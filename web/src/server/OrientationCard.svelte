<script lang="ts">
  // Which way a device's map faces: a tree's front, or a flat layout's bottom (any angle,
  // plus a mirror), as on the scan page's Review screen. While it's being set the LEDs
  // show it (a white stripe at the front; the bottom edge white and the left side red),
  // which stops what was playing; saving or cancelling turns them off. Every effect
  // follows the saved orientation.
  import { Compass } from "@lucide/svelte";
  import { onDestroy } from "svelte";
  import Alert from "../components/ui/Alert.svelte";
  import Button from "../components/ui/Button.svelte";
  import Card from "../components/ui/Card.svelte";
  import Toggle from "../components/ui/Toggle.svelte";
  import type { DeviceApi, Orientation } from "./api";
  import { coalesce } from "./coalesce";

  let { dev, shape, orientation, scanning, onchange }: {
    dev: DeviceApi; shape: "tree" | "flat"; orientation: Orientation; scanning: boolean;
    onchange: () => void;
  } = $props();

  const flat = $derived(shape === "flat");
  let editing = $state(false);
  let angle = $state(0);
  let mirror = $state(false);
  let saving = $state(false);
  let error = $state<string | null>(null);

  const saved = $derived("front_deg" in orientation
    ? { angle: Math.round(orientation.front_deg) % 360, mirror: false }
    : { angle: Math.round(orientation.rotate_deg) % 360, mirror: orientation.mirror });
  const dirty = $derived(angle !== saved.angle || (flat && mirror !== saved.mirror));
  const summary = $derived(flat
    ? `Turned ${saved.angle}° anticlockwise${saved.mirror ? ", mirrored" : ""}`
    : `Front at ${saved.angle}°`);

  const leds = coalesce((cmd: Record<string, unknown>) => dev.leds(cmd), (e) => (error = e.message));

  function show() {
    void leds.push(flat ? { mode: "edge", rotate_deg: angle, mirror } : { mode: "stripe", front_deg: angle });
  }

  function start() {
    angle = saved.angle;
    mirror = saved.mirror;
    error = null;
    editing = true;
    show();
  }

  function turn(deg: number) {
    angle = (((angle + deg) % 360) + 360) % 360;
    show();
  }

  async function finish(save: boolean) {
    if (save) {
      saving = true;
      try {
        await dev.setOrientation(flat ? { rotate_deg: angle, mirror } : { front_deg: angle });
      } catch (e) {
        error = (e as Error).message;
        return;
      } finally {
        saving = false;
      }
    }
    editing = false;
    error = null;
    await leds.push({ mode: "off" });
    onchange();
  }

  onDestroy(() => {
    if (editing) void dev.leds({ mode: "off" }).catch(() => {});
  });
</script>

<Card title={flat ? "Bottom" : "Front"}>
  {#snippet actions()}
    {#if !editing}
      <Button size="sm" icon={Compass} disabled={scanning} onclick={start}
              title={scanning ? "A scan is using the LEDs" : "Shows it on the LEDs, stopping the effect"}>Set it</Button>
    {/if}
  {/snippet}
  {#if !editing}
    <p class="muted">{summary}. {flat ? "Effects that go up or across start from this bottom."
      : "Effects that go round the tree start here."}</p>
  {:else}
    <p class="muted">
      {#if flat}
        The LEDs show the bottom edge white and the left side red. Turn until the white is along
        the bottom; if the red is then on the right, mirror it (filmed from behind).
      {:else}
        A white stripe lights the LEDs facing the front. Turn it until it faces the room.
      {/if}
    </p>
    <input class="slider" type="range" min="0" max="359" step="1" bind:value={angle} oninput={show}
           aria-label={flat ? "Turn, in degrees anticlockwise" : "Front, in degrees"} />
    <div class="turns">
      {#if flat}
        <Button size="sm" title="A quarter turn clockwise" onclick={() => turn(-90)}>↻ 90°</Button>
        <Button size="sm" onclick={() => turn(-1)}>−1°</Button>
        <output class="mono">{angle}°</output>
        <Button size="sm" onclick={() => turn(1)}>+1°</Button>
        <Button size="sm" title="A quarter turn anticlockwise" onclick={() => turn(90)}>↺ 90°</Button>
      {:else}
        <Button size="sm" onclick={() => turn(-10)}>−10°</Button>
        <Button size="sm" onclick={() => turn(-1)}>−1°</Button>
        <output class="mono">{angle}°</output>
        <Button size="sm" onclick={() => turn(1)}>+1°</Button>
        <Button size="sm" onclick={() => turn(10)}>+10°</Button>
      {/if}
    </div>
    {#if flat}
      <Toggle checked={mirror} onchange={(v) => { mirror = v; show(); }}>Mirror</Toggle>
    {/if}
    <div class="row">
      <Button size="sm" variant="primary" disabled={!dirty || saving} onclick={() => finish(true)}>
        {saving ? "Saving…" : "Save"}</Button>
      <Button size="sm" onclick={() => finish(false)}>{dirty ? "Cancel" : "Done"}</Button>
    </div>
  {/if}
  {#if error}<Alert tone="bad">{error}</Alert>{/if}
</Card>

<style>
  p { margin: 0; font-size: var(--t-sm); }
  .slider { width: 100%; accent-color: var(--accent); }
  .turns { display: flex; align-items: center; justify-content: center; gap: var(--s2); }
  .turns output { min-width: 4.5ch; text-align: center; font-size: var(--t-lg); font-weight: 600; }
  .row { display: flex; gap: var(--s2); }
</style>
