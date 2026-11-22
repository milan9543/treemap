<script lang="ts">
  // Whether a device's controller answers: a dot and a word.
  import type { Device } from "./api";

  let { device, long = false }: { device: Device; long?: boolean } = $props();
  const s = $derived(device.status);
  const tone = $derived(s.alive === true ? "ok" : s.alive === false ? "bad" : "unknown");
  const text = $derived(s.alive === true ? "on" : s.alive === false ? "off" : "checking…");
</script>

<span class="status {tone}" title={s.error ?? ""}>
  <i></i>{text}{#if long && s.alive === false && s.error}<span class="why">: {s.error}</span>{/if}
</span>

<style>
  .status { display: inline-flex; align-items: center; gap: 6px; font-size: var(--t-sm); white-space: nowrap; }
  i { width: 8px; height: 8px; border-radius: 50%; background: var(--faint); }
  .ok i { background: var(--ok); box-shadow: 0 0 6px var(--ok); }
  .bad i { background: var(--bad); }
  .ok { color: var(--ok); }
  .bad { color: var(--bad); }
  .unknown { color: var(--muted); }
  .why { color: var(--muted); }
</style>
