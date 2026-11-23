<script lang="ts">
  // The server's own page (`treemap serve`): its devices (#/) and one device
  // (#/device/<id>).
  import { onMount } from "svelte";
  import Alert from "../components/ui/Alert.svelte";
  import { api, API_VERSION, type Info } from "./api";
  import DeviceList from "./DeviceList.svelte";
  import DevicePage from "./DevicePage.svelte";

  let route = $state(location.hash);
  let info = $state<Info | null>(null);
  let error = $state<string | null>(null);
  const deviceId = $derived(route.match(/^#\/device\/([\w-]+)/)?.[1] ?? null);

  onMount(() => {
    const onHash = () => (route = location.hash);
    window.addEventListener("hashchange", onHash);
    api.info().then((i) => {
      info = i;
      if (i.api !== API_VERSION) error = `This page is for API version ${API_VERSION}, the server has ${i.api}: reload it.`;
    }, (e) => (error = (e as Error).message));
    return () => window.removeEventListener("hashchange", onHash);
  });
</script>

<div class="shell">
  <header class="bar">
    <a class="brand" href="#/">treemap</a>
    <span class="muted">server</span>
    <span class="grow"></span>
    {#if info}<span class="muted mono">{info.server}</span>{/if}
  </header>
  <main class:full={!!deviceId}>
    {#if error}
      <div class="error"><Alert tone="bad">{error}</Alert></div>
    {:else if !info}
      <p class="muted loading">Connecting…</p>
    {:else if deviceId}
      {#key deviceId}<DevicePage id={deviceId} {info} />{/key}
    {:else}
      <DeviceList />
    {/if}
  </main>
</div>

<style>
  .shell { height: 100%; display: flex; flex-direction: column; }
  .bar { height: var(--topbar-h); flex: none; display: flex; align-items: center; gap: var(--s2); padding: 0 var(--s4);
    background: var(--surface); border-bottom: 1px solid var(--border); font-size: var(--t-sm); }
  .brand { color: var(--text); text-decoration: none; font-weight: 700; font-size: var(--t-lg); }
  .grow { flex: 1; }
  main { flex: 1; min-height: 0; overflow-y: auto; }
  main.full { overflow: hidden; }
  .error, .loading { padding: var(--s5); }
  @media (max-width: 860px) { main.full { overflow-y: auto; } }
</style>
