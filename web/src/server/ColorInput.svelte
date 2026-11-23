<script lang="ts">
  // A colour: one tap on a Christmas colour, or any colour from the picker.
  let { value, onchange, none = false }: {
    value: string;
    onchange: (hex: string) => void;
    none?: boolean; // offer black as "none" (a background)
  } = $props();

  const SWATCHES = [
    { hex: "#ff0000", name: "Red" },
    { hex: "#00be14", name: "Green" },
    { hex: "#ff8c00", name: "Gold" },
    { hex: "#ff963c", name: "Warm white" },
    { hex: "#ffffff", name: "White" },
  ];
  const swatches = $derived(none ? [{ hex: "#000000", name: "None" }, ...SWATCHES] : SWATCHES);
  const current = $derived(value.toLowerCase());
</script>

<div class="color">
  {#each swatches as s (s.hex)}
    <button type="button" class="sw" class:on={current === s.hex} class:none={s.hex === "#000000"}
            style:background={s.hex} title={s.name} aria-label={s.name} onclick={() => onchange(s.hex)}></button>
  {/each}
  <input type="color" value={current} title="Any colour" aria-label="Any colour"
         class:on={!swatches.some((s) => s.hex === current)} oninput={(e) => onchange(e.currentTarget.value)} />
</div>

<style>
  .color { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
  .sw { width: 20px; height: 20px; padding: 0; border-radius: 50%; cursor: pointer;
    border: 1px solid var(--border-strong); }
  .sw.none { background: repeating-linear-gradient(135deg, #000 0 3px, #2a2f38 3px 6px) !important; }
  .sw.on, input.on { outline: 2px solid var(--accent); outline-offset: 1px; }
  input { width: 30px; height: 22px; padding: 0 2px; border-radius: var(--r1); }
</style>
