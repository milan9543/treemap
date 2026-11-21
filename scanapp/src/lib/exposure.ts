// Sets the phone camera's exposure and white balance for the LEDs, in the scan's
// "exposure" phase (see treemap/api/app.py). The LEDs show white at the scan's brightness
// meanwhile; the server counts the LEDs in the uploaded frames.
//
// With manual exposure (most Android phones in Chrome): white balance is locked first,
// then each exposure is tried, shortest first, and the shortest that shows nearly as many
// LEDs as the best is kept. Shorter clips the LEDs' colours less. This is what
// treemap.cameras.check.fix_exposure does for IP Webcam.
//
// Otherwise: let automatic exposure settle on the LEDs, then lock it, if the phone can.
//
// Chrome details (spike 1.2): `exposureTime` is in 100 µs units; white balance only locks
// with a `colorTemperature`, which Chrome snaps to a preset.

const EXPOSURES_MS = [0.5, 1, 2, 4, 8, 16];
const ISO = 100;
const ENOUGH = 0.9; // of the most LEDs any exposure shows
const SETTLE_S = 0.3; // frames this soon after a change may still have the old exposure
const AUTO_SETTLE_MS = 2500;
const DAYLIGHT_K = 5000;

type Range = { min: number; max: number; step?: number };
interface Caps {
  exposureMode?: string[];
  exposureTime?: Range;
  iso?: Range;
  whiteBalanceMode?: string[];
  colorTemperature?: Range;
}
type Constraints = Record<string, unknown>;

export interface Step {
  ms: number;
  leds: number | null; // null: not tried yet
}

export interface Exposure {
  message: string; // for the server's log and the page
  settings: Constraints; // what the camera reports afterwards
  ok: boolean; // false: no LEDs were seen, or nothing could be set
}

export interface Probe {
  /** How many LEDs the frames taken at `since` or later show; 0 frames if none came. */
  probe: (since: number) => Promise<{ frames: number; leds: number }>;
  /** The newest frame's time (the clock `since` is on), or null if not filming. */
  mark: () => Promise<number | null>;
  /** Each exposure's count so far, for the page to show. */
  onStep: (steps: Step[]) => void;
  /** False once the scan has gone (stopped, or the page left). */
  alive: () => boolean;
}

export class Gone extends Error {}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const clamp = (v: number, r: Range) => Math.min(r.max, Math.max(r.min, v));

function caps(track: MediaStreamTrack): Caps {
  return (track.getCapabilities?.() ?? {}) as Caps;
}

async function apply(track: MediaStreamTrack, c: Constraints): Promise<boolean> {
  try {
    await track.applyConstraints({ advanced: [c as MediaTrackConstraintSet] });
    return true;
  } catch {
    return false;
  }
}

/** The camera settings that matter for the colours, as it reports them. */
export function cameraSettings(track: MediaStreamTrack): Constraints {
  const s = track.getSettings() as Constraints;
  const keep = ["width", "height", "frameRate", "exposureMode", "exposureTime", "iso",
                "whiteBalanceMode", "colorTemperature", "focusMode"];
  return Object.fromEntries(keep.filter((k) => s[k] !== undefined).map((k) => [k, s[k]]));
}

async function lockWhiteBalance(track: MediaStreamTrack, c: Caps): Promise<boolean> {
  if (!c.whiteBalanceMode?.includes("manual")) return false;
  if (!c.colorTemperature) return apply(track, { whiteBalanceMode: "manual" });
  // Keep what automatic white balance chose for the LEDs, if the phone says.
  const now = (track.getSettings() as Constraints).colorTemperature;
  const k = clamp(typeof now === "number" && now > 0 ? now : DAYLIGHT_K, c.colorTemperature);
  return apply(track, { whiteBalanceMode: "manual", colorTemperature: k });
}

export async function setExposure(track: MediaStreamTrack, p: Probe): Promise<Exposure> {
  const c = caps(track);
  const check = () => {
    if (!p.alive()) throw new Gone();
  };
  if (c.exposureMode?.includes("manual") && c.exposureTime) {
    return search(track, c, p, check);
  }
  // Auto, settle, lock.
  if (c.exposureMode?.includes("continuous")) await apply(track, { exposureMode: "continuous" });
  await sleep(AUTO_SETTLE_MS);
  check();
  const wb = await lockWhiteBalance(track, c);
  const locked = !!c.exposureMode?.includes("manual") && await apply(track, { exposureMode: "manual" });
  return {
    message: locked ? `exposure set automatically, then locked${wb ? "" : " (white balance stays automatic)"}`
      : "this camera can't hold its exposure, so it stays automatic: colours may drift",
    settings: cameraSettings(track),
    ok: locked,
  };
}

async function search(track: MediaStreamTrack, c: Caps, p: Probe,
                      check: () => void): Promise<Exposure> {
  const range = c.exposureTime!;
  const iso = c.iso ? { iso: clamp(ISO, c.iso) } : {};
  const units = [...new Set(EXPOSURES_MS.map((ms) => clamp(ms * 10, range)))];
  const steps: Step[] = units.map((u) => ({ ms: u / 10, leds: null }));
  const set = (u: number) => apply(track, { exposureMode: "manual", exposureTime: u, ...iso });

  const wb = await lockWhiteBalance(track, c);
  p.onStep(steps);
  for (const [i, u] of units.entries()) {
    check();
    if (!(await set(u))) {
      return { message: "couldn't set the camera's exposure", settings: cameraSettings(track), ok: false };
    }
    const t = await p.mark();
    if (t === null) throw new Error("The camera isn't filming.");
    check();
    const r = await p.probe(t + SETTLE_S);
    if (!r.frames) throw new Error("No frames reached the server.");
    steps[i] = { ...steps[i], leds: r.leds };
    p.onStep([...steps]);
  }
  const most = Math.max(...steps.map((s) => s.leds ?? 0));
  const seen = steps.map((s) => `${s.ms} ms ${s.leds}`).join(", ");
  if (most === 0) {
    await set(clamp(20, range)); // 2 ms: a middling guess
    return { message: `no LEDs seen at any exposure (${seen})`, settings: cameraSettings(track), ok: false };
  }
  const best = units[steps.findIndex((s) => (s.leds ?? 0) >= ENOUGH * most)];
  await set(best);
  return {
    message: `exposure ${best / 10} ms${"iso" in iso ? ` at ISO ${iso.iso}` : ""}` +
      `${wb ? "" : " (white balance stays automatic)"}; LEDs seen per exposure: ${seen}`,
    settings: cameraSettings(track),
    ok: true,
  };
}

/** Back to automatic exposure and white balance, for the preview between scans. */
export async function autoExposure(track: MediaStreamTrack): Promise<void> {
  const c = caps(track);
  if (c.exposureMode?.includes("continuous")) await apply(track, { exposureMode: "continuous" });
  if (c.whiteBalanceMode?.includes("continuous")) await apply(track, { whiteBalanceMode: "continuous" });
}

/** The phone's model and camera, which its measured colours are kept under. Every
 * Android phone calls its main camera "camera2 0, facing back", so the model is what
 * tells phones apart. */
export async function cameraId(label: string): Promise<string> {
  let model = "";
  try {
    const ua = (navigator as { userAgentData?: { getHighEntropyValues(h: string[]): Promise<{ model?: string }> } })
      .userAgentData;
    model = (await ua?.getHighEntropyValues(["model"]))?.model ?? "";
  } catch {
    /* not told */
  }
  return [model, label].filter(Boolean).join(" ") || "phone camera";
}
