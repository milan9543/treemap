<script lang="ts">
  // An effect's controls, built from how GET /effects describes its parameters.
  import type { EffectInfo, EffectParam, Params } from "./api";
  import { loadPalettes, palettes } from "./palettes.svelte";

  let { fx, values, onchange }: {
    fx: EffectInfo;
    values: Params;
    onchange: (name: string, value: unknown) => void;
  } = $props();

  const value = (p: EffectParam) => values[p.name] ?? p.default;
  const decimals = (p: EffectParam) => (p.kind === "int" ? 0 : p.step && p.step < 0.1 ? 2 : 1);
  const fmt = (p: EffectParam) => Number(value(p)).toFixed(decimals(p));
  const shown = (p: EffectParam) =>
    p.when.every((w) => w.values.includes(values[w.param] ?? fx.params.find((q) => q.name === w.param)?.default));

  $effect(() => { if (fx.params.some((p) => p.kind === "palette")) loadPalettes(); });
</script>

<div class="params">
  {#each fx.params.filter(shown) as p (p.name)}
    <label class="ctl" title={p.help}>
      <span>{p.label}</span>
      {#if p.kind === "color"}
        <input type="color" value={String(value(p))} oninput={(e) => onchange(p.name, e.currentTarget.value)} />
        <output></output>
      {:else if p.kind === "bool"}
        <input type="checkbox" checked={!!value(p)} onchange={(e) => onchange(p.name, e.currentTarget.checked)} />
        <output></output>
      {:else if p.kind === "choice"}
        <select value={String(value(p))} onchange={(e) => onchange(p.name, e.currentTarget.value)}>
          {#each p.choices as c (c)}<option value={c}>{c}</option>{/each}
        </select>
        <output></output>
      {:else if p.kind === "palette"}
        <select value={String(value(p))} onchange={(e) => onchange(p.name, e.currentTarget.value)}>
          {#each palettes.list as pl (pl.id)}<option value={pl.id}>{pl.name}</option>{/each}
        </select>
        <output></output>
      {:else}
        <input type="range" min={p.min ?? 0} max={p.max ?? 1} step={p.step ?? (p.kind === "int" ? 1 : "any")}
               value={Number(value(p))}
               oninput={(e) => onchange(p.name, p.kind === "int" ? parseInt(e.currentTarget.value, 10)
                 : parseFloat(e.currentTarget.value))} />
        <output class="mono">{fmt(p)}</output>
      {/if}
    </label>
  {/each}
</div>

<style>
  .params { display: flex; flex-direction: column; gap: var(--s2); }
  .ctl { display: grid; grid-template-columns: 96px 1fr 44px; align-items: center; gap: var(--s2);
    font-size: var(--t-sm); color: var(--muted); }
  .ctl input[type="checkbox"] { justify-self: start; }
  output { text-align: right; font-size: var(--t-xs); color: var(--text); }
</style>
