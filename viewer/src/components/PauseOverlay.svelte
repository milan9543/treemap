<script lang="ts">
  import { LogOut, Play, Square } from "@lucide/svelte";
  import * as controls from "../3d/controls";
  import { cancelJob } from "../lib/actions";
  import { app } from "../lib/state.svelte";
  import Button from "./ui/Button.svelte";
</script>

<div class="scrim">
  <div class="card">
    <h2>{app.scanning ? "Scan running" : "Walk mode"}</h2>
    <p>{app.scanning
      ? "The LEDs keep flashing while you're paused. Resume to keep walking, or stop the scan."
      : "Resume to look round with the mouse."}</p>
    <div class="buttons">
      <Button variant="primary" size="lg" icon={Play} full onclick={controls.lock}>Resume walking</Button>
      {#if app.scanning}
        <Button variant="danger" icon={Square} full onclick={cancelJob}>Stop scan</Button>
      {/if}
      <Button icon={LogOut} full onclick={() => controls.setWalking(false)}>Leave walk mode</Button>
    </div>
  </div>
</div>

<style>
  .scrim { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    background: rgba(5, 7, 10, 0.45); }
  .card { width: 320px; padding: var(--s4); background: var(--surface); border: 1px solid var(--border-strong);
    border-radius: var(--r2); box-shadow: var(--shadow); display: flex; flex-direction: column; gap: var(--s2); }
  h2 { margin: 0; font-size: var(--t-lg); }
  p { margin: 0 0 var(--s2); color: var(--muted); font-size: var(--t-sm); }
  .buttons { display: flex; flex-direction: column; gap: var(--s2); }
</style>
