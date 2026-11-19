<script lang="ts">
  import { PanelLeft, Settings, Square } from "@lucide/svelte";
  import { cancelJob, stopEffect } from "../lib/actions";
  import { app, save, setStep, STEPS, type Step } from "../lib/state.svelte";
  import Button from "./ui/Button.svelte";

  const steps = $derived(STEPS.filter((s) => s.id !== "tree" || app.sim));

  function badge(id: Step): string {
    if (id === "tree") return app.tree ? `${app.tree.led_count} LEDs` : "";
    if (id === "scan") return app.scanning && app.job.progress ? `round ${app.job.progress.round}` : "";
    if (id === "map") {
      const c = app.map?.counts;
      return c ? `${c.ok}/${app.map!.status.length}` : "";
    }
    return effectLabel(app.engine.running) ?? "";
  }

  function effectLabel(name: string | null): string | null {
    if (!name) return null;
    return app.effects?.effects.find((e) => e.name === name)?.label ?? name;
  }

  // What's lighting the LEDs right now, and how to stop it.
  const driving = $derived(
    app.scanning ? { label: "Scan", stop: cancelJob }
      : app.engine.running ? { label: effectLabel(app.engine.running)!, stop: stopEffect }
      : null);
  const output = $derived(app.effects?.output ?? "sim");

  function toggleSidebar() {
    app.sidebar = !app.sidebar;
    save("sidebar", app.sidebar);
  }
</script>

<header>
  <Button variant="ghost" size="sm" icon={PanelLeft} title="Show or hide the sidebar ([)" onclick={toggleSidebar} />
  <div class="brand" title={app.connected ? "Connected to the treemap server" : "Not connected to the server"}>
    <span class="dot" class:on={app.connected}></span>treemap
  </div>
  <nav aria-label="Steps">
    {#each steps as s (s.id)}
      {@const b = badge(s.id)}
      <button class:active={app.step === s.id} title="{s.label} ({s.key})" onclick={() => setStep(s.id)}>
        {s.label}{#if b}<span class="badge">{b}</span>{/if}
      </button>
    {/each}
  </nav>
  <div class="spacer"></div>
  <div class="driving" class:live={!!driving} title="What's sending colours to the LEDs ({output})">
    <span class="pulse"></span>
    {#if driving}
      <span>LEDs: <b>{driving.label}</b></span>
      <Button size="sm" variant="ghost" icon={Square} title="Stop" onclick={driving.stop} />
    {:else}
      <span class="muted">LEDs idle</span>
    {/if}
    <span class="out mono">→ {output}{app.ledFps ? ` · ${app.ledFps} fps` : ""}</span>
  </div>
  <Button variant="ghost" size="sm" icon={Settings} title="Settings and shortcuts" active={app.settings}
    onclick={() => (app.settings = !app.settings)} />
</header>

<style>
  header { height: var(--topbar-h); display: flex; align-items: center; gap: var(--s3); padding: 0 var(--s3);
    background: var(--surface); border-bottom: 1px solid var(--border); flex: none; }
  .brand { display: flex; align-items: center; gap: var(--s2); font-weight: 650; letter-spacing: 0.01em; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--bad); }
  .dot.on { background: var(--accent); box-shadow: 0 0 8px var(--accent); }
  nav { display: flex; gap: 2px; margin-left: var(--s3); }
  nav button { display: flex; align-items: center; gap: 6px; border: 0; background: transparent; color: var(--muted);
    padding: 6px 12px; border-radius: var(--r1); cursor: pointer; font-weight: 500; }
  nav button:hover { color: var(--text); background: var(--surface-2); }
  nav button.active { color: var(--text); background: var(--surface-3); }
  .badge { font: var(--t-xs) var(--mono); color: var(--muted); background: var(--surface-2);
    border: 1px solid var(--border); border-radius: 10px; padding: 0 6px; }
  nav button.active .badge { color: var(--accent); border-color: var(--accent-border); }
  .spacer { flex: 1; }
  .driving { display: flex; align-items: center; gap: var(--s2); font-size: var(--t-sm); padding: 3px 4px 3px 10px;
    border: 1px solid var(--border); border-radius: 20px; background: var(--surface-2); min-height: 30px; }
  .pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--faint); }
  .live .pulse { background: var(--accent); animation: pulse 1.4s infinite; }
  .out { color: var(--faint); font-size: var(--t-xs); padding-right: 8px; }
  @keyframes pulse { 50% { opacity: 0.3; } }
  @media (max-width: 900px) { .out, .badge { display: none; } }
</style>
