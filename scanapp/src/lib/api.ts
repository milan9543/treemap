// The `treemap serve` API (treemap/api/app.py), reached over the LAN from this HTTPS page.
//
// Chrome lets an HTTPS page fetch a plain-HTTP private address once the user grants the
// local network permission. Every fetch must come from the page itself: a worker's
// fetches to the LAN fail even with the permission (spike 1.1).

export const API_VERSION = 1;
export const DEFAULT_PORT = 8765;

export type Shape = "tree" | "flat";
export type Counts = { ok: number; interpolated: number; failed: number };

export interface Info {
  api: number;
  server: string;
  shape: Shape;
  output: string;
  led_count: number;
  controllers: { host: string; start: number; count: number; reverse: boolean }[];
  map: null | { led_count: number; fits: boolean; shape: Shape; created: string | null; counts: Counts };
  busy: "scan" | "effect" | "leds" | null;
  leds: string | null;
  effect: string | null;
}

export type Phase = "countdown" | "exposure" | "colours" | "flashing" | "solving" | "status";

export interface ScanState {
  id: number;
  status: "idle" | "running" | "done" | "cancelled" | "error";
  message: string;
  error: string | null;
  phase: Phase | null;
  round: number | null;
  remaining: number | null;
  frames: number | null;
  identified: number | null;
  counts: Counts | null;
  frames_received: number;
  led_status?: string; // one letter per LED: o ok, i interpolated, f failed
  colours: ColourCheck | null; // once measured, for the rest of the scan
}

export type ColourName = "red" | "green" | "blue" | "white";

/** How the phone sees the code's colours, measured in the scan's "colours" phase. */
export interface ColourCheck {
  ok: boolean; // every colour read right often enough (85%)
  read_right: Record<ColourName, number | null>; // share, 0-1; null: not seen
  seen: Record<ColourName, number>; // LEDs seen per frame
  tips: string[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** "192.168.1.20" → "http://192.168.1.20:8765"; a full URL is kept (without a trailing /). */
export function normaliseServer(text: string): string {
  let s = text.trim().replace(/\/+$/, "").replace(/\/api\/v1$/, "");
  if (!s) return s;
  if (!/^https?:\/\//i.test(s)) s = "http://" + s;
  try {
    const u = new URL(s);
    if (!u.port && u.protocol === "http:") u.port = String(DEFAULT_PORT);
    return u.origin;
  } catch {
    return s;
  }
}

/** Chrome reaches IP addresses and .local names without help; any other name needs
 * `targetAddressSpace: "local"` on the fetch. */
function needsAddressSpace(server: string): boolean {
  try {
    const host = new URL(server).hostname;
    return !(/^[\d.]+$/.test(host) || host.includes(":") || host.endsWith(".local") ||
      host === "localhost" || location.hostname === host);
  } catch {
    return false;
  }
}

export class Api {
  readonly base: string;
  private extra: Record<string, string>;

  constructor(readonly server: string) {
    this.base = server + "/api/v1";
    this.extra = needsAddressSpace(server) ? { targetAddressSpace: "local" } : {};
  }

  async call<T>(method: string, path: string, body?: unknown | ArrayBuffer): Promise<T> {
    const init: RequestInit = { method, cache: "no-store", ...this.extra };
    if (body instanceof ArrayBuffer) {
      init.body = body;
      init.headers = { "Content-Type": "application/octet-stream" };
    } else if (body !== undefined) {
      init.body = JSON.stringify(body);
      init.headers = { "Content-Type": "application/json" };
    }
    let res: Response;
    try {
      res = await fetch(this.base + path, init);
    } catch {
      throw new ApiError(0, `Can't reach the server at ${this.server}.`);
    }
    let data: unknown = null;
    try {
      data = await res.json();
    } catch {
      /* an empty or non-JSON body */
    }
    if (!res.ok) {
      const msg = (data as { error?: string } | null)?.error ?? `HTTP ${res.status}`;
      throw new ApiError(res.status, msg);
    }
    return data as T;
  }

  info = () => this.call<Info>("GET", "/info");
  leds = (cmd: Record<string, unknown>) => this.call<{ mode: string; seconds?: number }>("POST", "/leds", cmd);
  scanStart = (settings: { shape: Shape; rounds?: number; camera?: string }) =>
    this.call<{ id: number }>("POST", "/scan/start", settings);
  scanStop = () => this.call<{ stopping: boolean }>("POST", "/scan/stop", {});
  scanState = () => this.call<ScanState>("GET", "/scan/state");
  frames = (batch: ArrayBuffer) => this.call<{ frames: number }>("POST", "/scan/frames", batch);
  /** How many LEDs the frames taken at `since` or later show (median per frame). */
  exposureProbe = (since: number, frames = 6) =>
    this.call<{ frames: number; leds: number }>("POST", "/scan/exposure-probe", { since, frames });
  cameraReady = (body: { message: string; settings: Record<string, unknown> }) =>
    this.call<{ ok: boolean }>("POST", "/scan/camera-ready", body);
}
