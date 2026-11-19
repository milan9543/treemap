// Long-running work (scan, reconstruct, evaluate, fixing one LED) runs as a job on the
// server, one at a time; its state arrives as {"type": "job"} messages.
import { events, jobActive, state } from "../state";
import type { JobState } from "../types";
import { $, esc } from "../util";
import { NOT_CONNECTED, connected, on, send } from "../ws";

const SCAN_PANEL_JOBS = ["scan", "reconstruct"];
let lastJobKind: string | null = null;

export const jobTarget = (kind: string | null) => (kind && SCAN_PANEL_JOBS.includes(kind) ? "sc" : "mp");

export function setJobLine(target: string, html: string, kind = ""): void {
  const el = $(`${target}-job`);
  el.innerHTML = html;
  el.className = `jobline ${kind}`;
}

export function startJob(kind: string, params: Record<string, unknown> = {}): void {
  lastJobKind = kind;
  if (!connected()) {
    setJobLine(jobTarget(kind), NOT_CONNECTED, "bad");
    return;
  }
  setJobLine(jobTarget(kind), "Starting…");
  send({ type: "job.start", job: kind, params });
}

export const cancelJob = () => send({ type: "job.cancel" });

const countsText = (c: Record<string, number>) =>
  `${c.ok} ok · ${c.interpolated} interpolated · ${c.failed} failed`;

function runningText(st: JobState): string {
  if (st.kind === "scan") {
    const p = st.progress;
    if (!p) return st.message || "Starting the scan…";
    if (p.phase === "flashing") {
      return `Round ${p.round}: flashing, ${p.remaining?.toFixed(0)} s left · ${p.identified} LEDs identified ` +
        `in ${p.frames} photos` + (p.frames ? "" : " (is the phone filming the tree?)");
    }
    if (p.phase === "solving") return `Round ${p.round}: solving positions from ${p.identified} LEDs…`;
    return `Round ${p.round}: ` + (p.counts ? countsText(p.counts) : p.message || "no map yet") +
      ". Walk to the red parts; the next round starts shortly.";
  }
  if (st.message) return st.message;
  const index = st.params?.index;
  return ({
    reconstruct: "Reconstructing…", evaluate: "Evaluating…",
    interpolate: `Interpolating LED ${index}…`, measure: `Measuring LED ${index} again…`,
  } as Record<string, string>)[st.kind ?? ""] || "Working…";
}

function doneText(st: JobState): string {
  const r = st.result || {};
  if (st.kind === "scan" || st.kind === "reconstruct") {
    if (!r.counts) return "Scan stopped before any positions could be solved.";
    return `Map: ${countsText(r.counts)}. ${r.rounds} round${r.rounds === 1 ? "" : "s"}, ` +
      `${r.registered} camera views, reprojection error ${r.median_residual_px} px.`;
  }
  if (st.kind === "evaluate") return "";
  return `Map rebuilt: LED ${r.index} is now ${r.status}.`;
}

function progressBar(st: JobState): string {
  const p = st.progress;
  if (st.kind !== "scan" || !p || p.remaining === undefined) return "";
  const cfg = state.serverConfig?.config?.scan;
  const total = p.phase === "status" ? cfg?.status_s : cfg?.round_s;
  if (!total || p.phase === "solving") return "";
  const pct = 100 * (1 - p.remaining / total);
  return `<div class="bar ${p.phase === "status" ? "status" : ""}"><i style="width: ${pct.toFixed(1)}%"></i></div>`;
}

function onJob(st: JobState): void {
  state.job = st;
  events.emit("job", st);
  if (!st.kind) return;
  const target = jobTarget(st.kind);
  if (jobActive()) setJobLine(target, esc(runningText(st)) + progressBar(st));
  else if (st.status === "error") setJobLine(target, esc(st.error), "bad");
  else if (st.status === "cancelled") {
    setJobLine(target, st.kind === "scan" ? "Stopped; finished rounds were kept. Start again to add more." : "Stopped.");
  } else if (st.status === "done") setJobLine(target, esc(doneText(st)), "good");
}

export function setupJobs(): void {
  on("job", onJob);
  on("job.rejected", (msg) => setJobLine(jobTarget(lastJobKind), esc(msg.error), "bad"));
}
