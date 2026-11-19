<script lang="ts">
  // Feedback for the jobs a step owns: running text, then the outcome, or why it was refused.
  import { app } from "../lib/state.svelte";
  import type { JobState } from "../lib/types";
  import Alert from "./ui/Alert.svelte";

  let { kinds }: { kinds: string[] } = $props();

  const counts = (c: Record<string, number>) => `${c.ok} ok · ${c.interpolated} interpolated · ${c.failed} failed`;

  function running(st: JobState): string {
    const index = st.params?.index;
    return ({
      scan: "Scanning…", reconstruct: "Solving positions from the saved rounds…",
      interpolate: `Interpolating LED ${index}…`, measure: `Measuring LED ${index} again…`,
    } as Record<string, string>)[st.kind ?? ""] ?? st.message ?? "Working…";
  }

  function done(st: JobState): string {
    const r = st.result ?? {};
    if (st.kind === "scan" || st.kind === "reconstruct") {
      if (!r.counts) return "Stopped before any positions could be solved.";
      return `Map: ${counts(r.counts)}. ${r.rounds} round${r.rounds === 1 ? "" : "s"}, ` +
        `${r.registered} camera views, reprojection error ${r.median_residual_px} px.`;
    }
    return `Map rebuilt: LED ${r.index} is now ${r.status}.`;
  }

  const job = $derived(app.job);
  const mine = $derived(!!job.kind && kinds.includes(job.kind));
  const refused = $derived(app.jobError && kinds.includes(app.jobError.kind ?? "") ? app.jobError.error : null);
</script>

{#if refused}
  <Alert tone="bad">{refused}</Alert>
{:else if mine && job.status === "running" && job.kind !== "scan"}
  <Alert tone="info">{running(job)}</Alert>
{:else if mine && job.status === "error"}
  <Alert tone="bad">{job.error}</Alert>
{:else if mine && job.status === "cancelled"}
  <Alert tone="info">{job.kind === "scan" ? "Stopped. Finished rounds were kept; start again to add more." : "Stopped."}</Alert>
{:else if mine && job.status === "done"}
  <Alert tone="ok">{done(job)}</Alert>
{/if}
