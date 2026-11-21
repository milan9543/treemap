<script lang="ts">
  import Connect from "./screens/Connect.svelte";
  import Scan from "./screens/Scan.svelte";
  import Wiring from "./screens/Wiring.svelte";
  import { app } from "./lib/state.svelte";
</script>

{#if app.screen === "scan" && app.api}
  <Scan api={app.api} />
{:else if app.screen === "wiring" && app.api}
  <Wiring api={app.api} />
{:else}
  <Connect />
{/if}
