// Sets the phone camera's exposure and white balance for the LEDs, in the scan's
// "exposure" phase (see treemap/api/app.py). Meanwhile the LEDs show the code's colours
// at the scan's brightness, each LED one of red, green, blue and white, and the server
// counts the LEDs in the uploaded frames. Blue is usually far dimmer to a camera than
// white, so an exposure only shows nearly every LED once it shows the blue ones too.
//
// With manual exposure (most Android phones in Chrome): white balance is locked first,
// then the steps of `ladder` are tried, darkest first, until two in a row show barely
// more LEDs than the best so far (so noise and glow at high ISO don't drag it brighter).
// The darkest that shows nearly as many LEDs as the best is kept: it clips the LEDs'
// colours least. "As many as the best", not "all": LEDs on the far side of the tree
// never show. Past 8 ms the ISO goes up instead of the exposure time, which would smear
// the LEDs as you walk. The page then lets the user pick another step (Scan.svelte).
//
// Otherwise: let automatic exposure settle on the LEDs, then lock it, if the phone can.
//
// Chrome details (spike 1.2): `exposureTime` is in 100 µs units; white balance only locks
// with a `colorTemperature`, which Chrome snaps to a preset.

const TIMES_MS = [0.5, 1, 2, 4, 8];
const ISO = 100;
const MORE_ISO = [200, 400, 800, 1600]; // at the longest time
const LONGER_MS = [16, 33]; // instead, for cameras without an ISO control
const ENOUGH = 0.95; // of the most LEDs any exposure shows
const GAIN = 0.05; // a brighter step must show this many more LEDs to count as better
const FLAT_STEPS = 2; // stop after this many steps in a row that weren't better
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
  iso: number | null; // null: the camera has no ISO control
  leds: number | null; // null: not tried yet
}

export interface Exposure {
  message: string; // for the server's log and the page
  settings: Constraints; // what the camera reports afterwards
  ok: boolean; // false: no LEDs were seen, or nothing could be set
  steps: Step[]; // the exposures to choose from; empty if the camera has no manual exposure
  chosen: number | null; // which of them is set
  whiteBalance: boolean; // locked
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

/** Whether the page can set this camera's exposure itself (else: auto, then lock). */
export function canSetExposure(track: MediaStreamTrack): boolean {
  const c = caps(track);
  return !!(c.exposureMode?.includes("manual") && c.exposureTime);
}

export function stepName(s: { ms: number; iso: number | null }): string {
  return `${s.ms} ms${s.iso === null ? "" : ` ISO ${s.iso}`}`;
}

/** Set one exposure. */
export function setStep(track: MediaStreamTrack, s: Step): Promise<boolean> {
  return apply(track, {
    exposureMode: "manual", exposureTime: s.ms * 10, ...(s.iso === null ? {} : { iso: s.iso }) });
}

/** Set one exposure and count the LEDs it shows. Throws if it can't. */
export async function tryStep(track: MediaStreamTrack, s: Step, p: Probe): Promise<number> {
  if (!p.alive()) throw new Gone();
  if (!(await setStep(track, s))) throw new Error("couldn't set the camera's exposure");
  const t = await p.mark();
  if (t === null) throw new Error("The camera isn't filming.");
  if (!p.alive()) throw new Gone();
  const r = await p.probe(t + SETTLE_S);
  if (!r.frames) throw new Error("No frames reached the server.");
  return r.leds;
}

/** What was set, for the server's log. */
export function describe(e: Exposure, how: string): string {
  const s = e.chosen === null ? null : e.steps[e.chosen];
  if (!s) return e.message;
  const seen = e.steps.filter((x) => x.leds !== null).map((x) => `${stepName(x)}: ${x.leds}`).join(", ");
  return `exposure ${stepName(s)} (${how})${e.whiteBalance ? "" : ", white balance stays automatic"}` +
    (seen ? `; LEDs seen per exposure: ${seen}` : "");
}

/** Find the exposure (see the top of this file). */
export async function setExposure(track: MediaStreamTrack, p: Probe): Promise<Exposure> {
  const c = caps(track);
  if (canSetExposure(track)) return search(track, c, p);
  // Auto, settle, lock.
  if (c.exposureMode?.includes("continuous")) await apply(track, { exposureMode: "continuous" });
  await sleep(AUTO_SETTLE_MS);
  if (!p.alive()) throw new Gone();
  const wb = await lockWhiteBalance(track, c);
  const locked = !!c.exposureMode?.includes("manual") && await apply(track, { exposureMode: "manual" });
  return {
    message: locked ? `exposure set automatically, then locked${wb ? "" : " (white balance stays automatic)"}`
      : "this camera can't hold its exposure, so it stays automatic: colours may drift",
    settings: cameraSettings(track), ok: locked, steps: [], chosen: null, whiteBalance: wb,
  };
}

async function search(track: MediaStreamTrack, c: Caps, p: Probe): Promise<Exposure> {
  const steps = ladder(c);
  const wb = await lockWhiteBalance(track, c);
  p.onStep(steps);
  let most = 0;
  let flat = 0; // steps in a row that added little: brighter won't show more LEDs
  for (const [i, s] of steps.entries()) {
    const leds = await tryStep(track, s, p);
    steps[i] = { ...s, leds };
    p.onStep([...steps]);
    flat = most > 0 && leds < most * (1 + GAIN) ? flat + 1 : 0;
    most = Math.max(most, leds);
    if (flat >= FLAT_STEPS) break;
  }
  const result = { settings: {}, steps, whiteBalance: wb };
  if (most === 0) {
    const guess = Math.min(4, steps.length - 1); // 8 ms at ISO 100: a middling guess
    await setStep(track, steps[guess]);
    return { ...result, settings: cameraSettings(track), chosen: guess, ok: false,
             message: "no LEDs seen at any exposure" };
  }
  const chosen = steps.findIndex((s) => s.leds !== null && s.leds >= ENOUGH * most);
  await setStep(track, steps[chosen]);
  return { ...result, settings: cameraSettings(track), chosen, ok: true, message: "" };
}

/** Set a remembered exposure without searching (white balance is locked first). */
export async function useExposure(track: MediaStreamTrack, saved: { ms: number; iso: number | null }): Promise<Exposure> {
  const c = caps(track);
  const steps = ladder(c);
  let chosen = steps.findIndex((s) => s.ms === saved.ms && s.iso === saved.iso);
  if (chosen < 0) {
    steps.push({ ...saved, leds: null });
    chosen = steps.length - 1;
  }
  const wb = await lockWhiteBalance(track, c);
  const ok = await setStep(track, steps[chosen]);
  return { message: ok ? "" : "couldn't set the camera's exposure", settings: cameraSettings(track),
           ok, steps, chosen, whiteBalance: wb };
}

const savedKey = (camera: string) => `exposure:${camera}`;

/** The exposure last used with this camera, if any. */
export function savedExposure(camera: string): { ms: number; iso: number | null } | null {
  try {
    const v = JSON.parse(localStorage.getItem(savedKey(camera)) ?? "null");
    return typeof v?.ms === "number" ? { ms: v.ms, iso: typeof v.iso === "number" ? v.iso : null } : null;
  } catch {
    return null;
  }
}

export function saveExposure(camera: string, s: { ms: number; iso: number | null }): void {
  try {
    localStorage.setItem(savedKey(camera), JSON.stringify({ ms: s.ms, iso: s.iso }));
  } catch {
    /* not remembered */
  }
}

/** The exposures to try, darkest first, within what the camera can do. */
function ladder(c: Caps): Step[] {
  const ms = (t: number) => clamp(t * 10, c.exposureTime!) / 10;
  const iso = c.iso ? (v: number) => clamp(v, c.iso!) : null;
  const steps: Step[] = TIMES_MS.map((t) => ({ ms: ms(t), iso: iso?.(ISO) ?? null, leds: null }));
  const longest = steps[steps.length - 1].ms;
  if (iso) steps.push(...MORE_ISO.map((v) => ({ ms: longest, iso: iso(v), leds: null })));
  else steps.push(...LONGER_MS.map((t) => ({ ms: ms(t), iso: null, leds: null })));
  return steps.filter((s, i) => !steps.slice(0, i).some((o) => o.ms === s.ms && o.iso === s.iso));
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
