<script lang="ts">
  // An effect's controls, built from how GET /effects describes its parameters: its own
  // settings first, then the ones many effects share, each in its section: colours (one
  // colour or a palette), background, sparkle. A setting that only matters for some
  // values of another (`when`) is hidden otherwise.
  import Section from "../components/ui/Section.svelte";
  import Segmented from "../components/ui/Segmented.svelte";
  import Toggle from "../components/ui/Toggle.svelte";
  import type { EffectInfo, EffectParam, Params } from "./api";
  import ColorInput from "./ColorInput.svelte";
  import PalettePicker from "./PalettePicker.svelte";

  let { fx, values, onchange }: {
    fx: EffectInfo;
    values: Params;
    onchange: (name: string, value: unknown) => void;
  } = $props();

  const SECTIONS = [
    { group: "colours", title: "Colours", head: "colors" },
    { group: "background", title: "Background", head: null },
    { group: "sparkle", title: "Sparkle", head: "sparkle" },
  ];

  const value = (p: EffectParam) => values[p.name] ?? p.default;
  const byName = (name: string) => fx.params.find((q) => q.name === name);
  const decimals = (p: EffectParam) => (p.kind === "int" ? 0 : p.step && p.step < 0.1 ? 2 : 1);
  const fmt = (p: EffectParam) => Number(value(p)).toFixed(decimals(p));
  const shown = (p: EffectParam) =>
    p.when.every((w) => { const q = byName(w.param); return !q || w.values.includes(value(q)); });

  const own = $derived(fx.params.filter((p) => !p.group && shown(p)));
  const sections = $derived(SECTIONS.map((s) => ({
    ...s,
    head: s.head ? byName(s.head) ?? null : null,
    rows: fx.params.filter((p) => p.group === s.group && p.name !== s.head && shown(p)),
  })).filter((s) => s.head || s.rows.length));
</script>

{#snippet row(p: EffectParam)}
  {#if p.kind === "palette"}
    <div class="ctl wide" title={p.help}>
      <span>{p.label}</span>
      <PalettePicker value={String(value(p))} fallback={String(p.default)} onchange={(id) => onchange(p.name, id)} />
    </div>
  {:else if p.kind === "color"}
    <div class="ctl wide" title={p.help}>
      <span>{p.label}</span>
      <ColorInput value={String(value(p))} none={p.name === "background"} onchange={(hex) => onchange(p.name, hex)} />
    </div>
  {:else}
    <label class="ctl" title={p.help}>
      <span>{p.label}</span>
      {#if p.kind === "bool"}
        <input type="checkbox" checked={!!value(p)} onchange={(e) => onchange(p.name, e.currentTarget.checked)} />
        <output></output>
      {:else if p.kind === "choice"}
        <select value={String(value(p))} onchange={(e) => onchange(p.name, e.currentTarget.value)}>
          {#each p.choices as c (c)}<option value={c}>{c}</option>{/each}
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
  {/if}
{/snippet}

<div class="params">
  {#each own as p (p.name)}{@render row(p)}{/each}

  {#each sections as s (s.group)}
    <Section title={s.title}>
      {#snippet control()}
        {#if s.head?.kind === "bool"}
          <Toggle checked={!!value(s.head)} title={s.head.help} onchange={(on) => onchange(s.head!.name, on)} />
        {:else if s.head?.kind === "choice"}
          <Segmented size="sm" value={String(value(s.head))} onchange={(v) => onchange(s.head!.name, v)}
                     options={s.head.choices.map((c) => ({ value: c, label: c === "one" ? "One colour" : c === "palette" ? "Palette" : c }))} />
        {/if}
      {/snippet}
      {#each s.rows as p (p.name)}{@render row(p)}{/each}
    </Section>
  {/each}
</div>

<style>
  .params { display: flex; flex-direction: column; gap: var(--s2); }
  .ctl { display: grid; grid-template-columns: 96px 1fr 44px; align-items: center; gap: var(--s2);
    font-size: var(--t-sm); color: var(--muted); }
  .ctl.wide { grid-template-columns: 96px 1fr; }
  .ctl input[type="checkbox"] { justify-self: start; }
  output { text-align: right; font-size: var(--t-xs); color: var(--text); }
</style>
