// How the scan's progress reads in the Scan step and the walk-mode HUD.
import { app } from "./state.svelte";
import type { ScanProgress } from "./types";

export const PHASES: Record<ScanProgress["phase"], string> = {
  countdown: "Starting in",
  exposure: "Setting the camera's exposure…",
  colours: "Measuring the colours…",
  flashing: "Flashing codes",
  solving: "Solving positions…",
  status: "Showing the result",
};

export const roundLabel = (p: ScanProgress) => (p.round === 0 ? "Getting ready" : `Round ${p.round}`);

/** Seconds the current phase lasts, for its progress bar (undefined: no bar). */
export function phaseTotal(p: ScanProgress): number | undefined {
  const scan = app.config?.config?.scan;
  if (p.remaining === undefined) return undefined;
  return p.phase === "countdown" ? scan?.countdown_s : p.phase === "status" ? scan?.status_s
    : p.phase === "flashing" ? scan?.round_s : undefined;
}
