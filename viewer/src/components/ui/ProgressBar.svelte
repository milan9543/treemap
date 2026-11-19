<script lang="ts">
  let { value, tone = "accent" }: { value: number; tone?: "accent" | "warn" } = $props();
</script>

<div class="bar" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
  <i class={tone} style="width: {Math.max(0, Math.min(1, value)) * 100}%"></i>
</div>

<style>
  .bar { height: 6px; background: var(--surface-3); border-radius: 4px; overflow: hidden; }
  i { display: block; height: 100%; transition: width 0.25s linear; }
  .accent { background: var(--accent); }
  .warn { background: var(--warn); }
</style>
