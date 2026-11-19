<script lang="ts">
  import { X } from "@lucide/svelte";
  import { app } from "../lib/state.svelte";
  import { yamlish } from "../lib/util";
  import Button from "./ui/Button.svelte";

  const SHORTCUTS: [string, string][] = [
    ["1 – 4", "Tree, Scan, Map, Effects"],
    ["[", "Show or hide the sidebar"],
    ["t", "Truth → Scanned → Compare"],
    ["f", "Walk mode on or off"],
    ["W A S D", "Walk (mouse looks round)"],
    ["Space / Shift", "Up / down while walking"],
    ["Esc", "Free the mouse (pauses walking)"],
    ["r", "Reset the view"],
    ["o c b w", "Layers: unlit LEDs, cone, branches, wire"],
  ];
</script>

<svelte:window onkeydown={(e) => { if (e.key === "Escape" && app.settings) app.settings = false; }} />

{#if app.settings}
  <div class="scrim" role="presentation" onclick={() => (app.settings = false)}></div>
  <aside aria-label="Settings">
    <header>
      <h2>Settings</h2>
      <Button variant="ghost" size="sm" icon={X} title="Close" onclick={() => (app.settings = false)} />
    </header>
    <section>
      <h3>Keyboard</h3>
      <table>
        <tbody>
          {#each SHORTCUTS as [keys, what]}
            <tr><td class="keys">{#each keys.split(" ") as k}{#if k === "/" || k === "–"}<span class="muted"> {k} </span>{:else}<kbd>{k}</kbd> {/if}{/each}</td><td>{what}</td></tr>
          {/each}
        </tbody>
      </table>
    </section>
    <section>
      <h3>Configuration</h3>
      <p class="muted">From <code>{app.config?.config_source ?? "built-in defaults (no config.yaml)"}</code>, merged with the defaults. Edit the file and restart <code>treemap sim view</code> to change it.</p>
      {#if app.config?.config}
        <pre>{yamlish(app.config.config).trimStart()}</pre>
      {:else}
        <p class="muted">This server doesn't share its configuration.</p>
      {/if}
    </section>
  </aside>
{/if}

<style>
  .scrim { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35); z-index: 40; }
  aside { position: fixed; top: 0; right: 0; bottom: 0; width: min(440px, 100vw); z-index: 41; overflow: auto;
    background: var(--surface); border-left: 1px solid var(--border); box-shadow: var(--shadow);
    padding: var(--s4); display: flex; flex-direction: column; gap: var(--s5); }
  header { display: flex; align-items: center; justify-content: space-between; }
  h2 { margin: 0; font-size: var(--t-xl); }
  h3 { margin: 0 0 var(--s2); font-size: var(--t-xs); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
  td { padding: 5px 4px; border-bottom: 1px solid var(--border); }
  .keys { white-space: nowrap; width: 1%; padding-right: var(--s4); }
  p { margin: 0 0 var(--s2); font-size: var(--t-sm); }
  pre { margin: 0; font: var(--t-xs)/1.5 var(--mono); color: var(--muted); background: var(--surface-2);
    border: 1px solid var(--border); border-radius: var(--r1); padding: var(--s2) var(--s3); overflow: auto; }
</style>
