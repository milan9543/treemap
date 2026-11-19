// The Scan panel: start and stop the free-moving scan, re-solve from the saved rounds.
import { setWalking } from "../controls";
import { events, jobActive, state } from "../state";
import { $, collapsible } from "../util";
import { cancelJob, setJobLine, startJob } from "./jobs";

function syncButtons(): void {
  const active = jobActive();
  const jobsOk = !!state.serverConfig?.jobs;
  $<HTMLButtonElement>("sc-start").disabled = active || !jobsOk;
  $<HTMLButtonElement>("sc-recon").disabled = active || !jobsOk;
  $<HTMLButtonElement>("sc-stop").disabled = !active;
}

export function setupScanPanel(): void {
  const cfg = state.serverConfig?.config;
  if (cfg) {
    $("sc-cam").textContent = `camera ${cfg.camera.type} · profile ${cfg.scan.profile}`;
    $("mp-evaluate").style.display = cfg.camera.type === "sim" ? "" : "none";
  }
  if (!state.serverConfig?.jobs) setJobLine("sc", "Scanning isn't available from this server.", "bad");
  $("sc-start").onclick = () => {
    const fresh = $<HTMLInputElement>("sc-fresh").checked;
    if (fresh && !confirm("Forget the earlier scan rounds and start from scratch?")) return;
    startJob("scan", { fresh });
    if (state.serverConfig?.config?.camera.type === "sim") setWalking(true);
  };
  $("sc-recon").onclick = () => startJob("reconstruct");
  $("sc-stop").onclick = () => cancelJob();
  collapsible("sc");
  events.on("job", syncButtons);
  syncButtons();
}
