<script lang="ts">
  import { Footprints, Play, RefreshCw, Square } from "@lucide/svelte";
  import * as controls from "../3d/controls";
  import JobStatus from "../components/JobStatus.svelte";
  import Button from "../components/ui/Button.svelte";
  import Card from "../components/ui/Card.svelte";
  import ProgressBar from "../components/ui/ProgressBar.svelte";
  import StepHeader from "../components/ui/StepHeader.svelte";
  import { cancelJob, startJob, startScan } from "../lib/actions";
  import { STATUS_COLORS } from "../lib/colors";
  import { PHASES, phaseTotal, roundLabel } from "../lib/scan";
  import { app } from "../lib/state.svelte";

  const p = $derived(app.scanning ? app.job.progress : null);
  const scanCfg = $derived(app.config?.config?.scan);
  const total = $derived(p ? phaseTotal(p) : undefined);
  const ready = $derived(p?.round === 0);

  function start() {
    if (app.map && !confirm("Start a new scan? The earlier scan's rounds are forgotten.")) return;
    startScan();
  }
</script>

<StepHeader title="Scan" description="Walk round the tree while every LED flashes its own colour code. Each round ends with the result on the tree." />

{#if p}
  <Card title="Scanning">
    <div class="phase">
      <span class="round">{roundLabel(p)}</span>
      <span>{PHASES[p.phase]}</span>
      {#if p.remaining !== undefined}<span class="mono muted">{Math.ceil(p.remaining)} s</span>{/if}
    </div>
    {#if total && p.remaining !== undefined}
      <ProgressBar value={1 - p.remaining / total} tone={p.phase === "status" ? "warn" : "accent"} />
    {/if}
    {#if ready}
      <p class="hint">
        {#if p.phase === "countdown"}Point the camera at the LEDs and keep it there.
        {:else}The LEDs show white, then red, green and blue while the camera adjusts.{/if}
      </p>
    {:else}
    <div class="stats">
      <div><b class="mono">{p.identified ?? 0}</b><span>LEDs identified</span></div>
      <div><b class="mono">{p.frames ?? 0}</b><span>photos</span></div>
      <div><b class="mono">{app.phoneFps}</b><span>photos / s</span></div>
    </div>
    {/if}
    {#if p.phase === "status"}
      {#if p.counts}
        <div class="counts">
          {#each Object.entries(p.counts) as [s, n]}<span><i style="background: {STATUS_COLORS[s]}"></i>{n} {s}</span>{/each}
        </div>
        <p class="hint">Walk to the red parts of the tree; the next round starts in a moment.</p>
      {:else if p.message}
        <p class="hint warn">{p.message}</p>
      {/if}
    {:else if p.phase === "flashing" && (p.frames ?? 0) === 0 && app.sim}
      <p class="hint warn">No photos yet: the scan films through the viewer's phone.</p>
    {/if}
    <div class="buttons">
      <Button variant="danger" icon={Square} onclick={cancelJob}>Stop scan</Button>
      {#if app.sim && !app.walking}
        <Button icon={Footprints} onclick={() => controls.setWalking(true)}>Walk</Button>
      {/if}
    </div>
  </Card>
{:else}
  <Card>
    <ol class="howto">
      <li>Press <b>Start</b>{#if (scanCfg?.countdown_s ?? 0) > 0} and point the camera at the LEDs within
        {scanCfg?.countdown_s} s{/if}.{#if !app.sim} The phone's exposure and colours are set first.{/if}
        Then every LED flashes its own code of red, green and blue.</li>
      {#if app.sim}
        <li>Walk round the tree: <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> move, the mouse looks round.
          The phone films what you see.</li>
      {:else}
        <li>Walk round the tree filming it with the phone.</li>
      {/if}
      <li>About every {scanCfg?.round_s ?? 12} s the tree shows the result: green placed, yellow filled in,
        red unknown. Walk to the red parts.</li>
    </ol>
    <Button variant="primary" size="lg" icon={Play} full disabled={!app.jobsAvailable || app.jobActive} onclick={start}>
      Start scanning
    </Button>
    <p class="hint">Each scan starts over; its rounds build on each other.</p>
    {#if !app.jobsAvailable}<p class="hint warn">Scanning isn't available from this server.</p>{/if}
  </Card>
{/if}

<JobStatus kinds={["scan", "reconstruct"]} />

{#if app.map && !p}
  <Card title="Saved scan">
    <dl class="facts">
      <div><dt>Rounds</dt><dd class="mono">{app.map.rounds ?? "–"}</dd></div>
      <div><dt>Placed</dt><dd class="mono">{app.map.counts?.ok ?? 0}/{app.map.status.length}</dd></div>
      <div><dt>Updated</dt><dd>{app.map.created ? new Date(app.map.created).toLocaleTimeString() : "–"}</dd></div>
    </dl>
    <Button icon={RefreshCw} disabled={!app.jobsAvailable || app.jobActive} title="Solve the positions again from the saved rounds"
      onclick={() => startJob("reconstruct")}>Solve again</Button>
  </Card>
{/if}

<style>
  .phase { display: flex; align-items: baseline; gap: var(--s3); }
  .phase .mono { margin-left: auto; }
  .round { font-weight: 600; font-size: var(--t-lg); }
  .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--s2); }
  .stats div { display: flex; flex-direction: column; }
  .stats b { font-size: var(--t-xl); font-weight: 600; }
  .stats span { font-size: var(--t-xs); color: var(--muted); }
  .counts { display: flex; gap: var(--s3); flex-wrap: wrap; font: var(--t-sm) var(--mono); }
  .counts span { display: inline-flex; align-items: center; gap: 5px; }
  .counts i { width: 9px; height: 9px; border-radius: 50%; }
  .hint { margin: 0; font-size: var(--t-sm); color: var(--muted); }
  .hint.warn { color: var(--warn); }
  .buttons { display: flex; gap: var(--s2); }
  .howto { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 4px; font-size: var(--t-sm); color: var(--muted); }
  .howto b { color: var(--text); }
  .facts { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--s2); margin: 0; }
  .facts div { display: flex; flex-direction: column; }
  dt { font-size: var(--t-xs); color: var(--muted); }
  dd { margin: 0; }
</style>
