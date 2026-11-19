<script lang="ts">
  import { setEffectParam } from "../lib/actions";
  import { app } from "../lib/state.svelte";
  import type { EffectInfo, EffectParam } from "../lib/types";

  let { fx }: { fx: EffectInfo } = $props();

  // What the user set locally wins over the engine's echo while they drag.
  let local = $state<Record<string, unknown>>({});
  $effect(() => { void fx.name; local = {}; });
  const value = (p: EffectParam) => (p.name in local ? local[p.name] : app.engine.params?.[p.name]);

  function set(p: EffectParam, v: unknown) {
    local[p.name] = v;
    setEffectParam(p.name, v);
  }
  const fmt = (p: EffectParam, v: unknown) =>
    p.kind === "int" ? String(v) : (+(v as number)).toFixed(p.step && p.step < 0.1 ? 2 : 1);
</script>

<div class="params">
  {#each fx.params as p (p.name)}
    <label class="ctl" title={p.help ?? ""}>
      <span>{p.label}</span>
      {#if p.kind === "color"}
        <input type="color" value={String(value(p))} oninput={(e) => set(p, e.currentTarget.value)} />
        <output></output>
      {:else if p.kind === "bool"}
        <input type="checkbox" checked={!!value(p)} onchange={(e) => set(p, e.currentTarget.checked)} />
        <output></output>
      {:else if p.kind === "choice"}
        <select value={String(value(p))} onchange={(e) => set(p, e.currentTarget.value)}>
          {#each p.choices ?? [] as c}<option value={c}>{c}</option>{/each}
        </select>
        <output></output>
      {:else}
        <input type="range" min={p.min} max={p.max} step={p.step ?? (p.kind === "int" ? 1 : "any")} value={Number(value(p))}
          oninput={(e) => set(p, p.kind === "int" ? parseInt(e.currentTarget.value, 10) : parseFloat(e.currentTarget.value))} />
        <output class="mono">{fmt(p, value(p))}</output>
      {/if}
    </label>
  {/each}
</div>

<style>
  .params { display: flex; flex-direction: column; gap: var(--s2); }
  .ctl { display: grid; grid-template-columns: 96px 1fr 44px; align-items: center; gap: var(--s2);
    font-size: var(--t-sm); color: var(--muted); }
  .ctl input[type=checkbox] { justify-self: start; }
  output { text-align: right; font-size: var(--t-xs); color: var(--text); }
</style>
