<script lang="ts">
  import { app } from "../lib/state.svelte";
  import Alert from "./ui/Alert.svelte";

  const expected = $derived(app.tree?.led_count ?? app.map?.status.length ?? null);
</script>

{#if (app.loaded && !app.connected) || app.sources.length > 1 || (app.frameLeds && expected && app.frameLeds !== expected)}
  <div class="banners">
    {#if app.loaded && !app.connected}
      <Alert tone="bad">Not connected to the treemap server; reconnecting. Is <code>treemap sim view</code> running?</Alert>
    {/if}
    {#if app.sources.length > 1}
      <Alert tone="warn">
        {app.sources.length} programs are sending colours at once, so the LEDs flicker between them:
        {#each app.sources as s, i}<code>{s}</code>{i < app.sources.length - 1 ? ", " : ""}{/each}.
        Stop all but one (Ctrl-C in its terminal).
      </Alert>
    {/if}
    {#if app.frameLeds && expected && app.frameLeds !== expected}
      <Alert tone="warn">
        Frames have {app.frameLeds} LEDs but the tree has {expected}: a command started before the tree
        changed is still sending the old number. Stop it (Ctrl-C in its terminal) and start it again.
      </Alert>
    {/if}
  </div>
{/if}

<style>
  .banners { display: flex; flex-direction: column; gap: var(--s1); padding: var(--s2) var(--s3);
    background: var(--surface); border-bottom: 1px solid var(--border); }
</style>
