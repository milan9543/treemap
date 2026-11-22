// The `treemap serve` API (treemap/api/app.py and device.py), reached over the LAN from
// this HTTPS page. The page scans one device: the server's QR code opens it with
// ?server=…&device=<id>, and every call but the server's info goes to that device.
//
// Chrome lets an HTTPS page fetch a plain-HTTP private address once the user grants the
// local network permission. Every fetch must come from the page itself: a worker's
// fetches to the LAN fail even with the permission (spike 1.1).

export const API_VERSION = 2;
export const DEFAULT_PORT = 8765;

export type Shape = "tree" | "flat";
export type Counts = { ok: number; interpolated: number; failed: number };

/** GET /info: the server itself. */
export interface ServerInfo {
  api: number;
  server: string;
  devices: number;
}

/** A device as GET /devices lists it: one WLED controller and its LEDs. */
export interface DeviceSummary {
  id: string;
  name: string;
  host: string;
  virtual: boolean;
  led_count: number | null; // null until its WLED has answered
  status: { alive: boolean | null; error: string | null };
  map?: Info["map"];
}

/** GET /devices/{id}: the device being scanned. */
export interface Info extends DeviceSummary {
  led_count: number;
  shape: Shape;
  map: null | {
    led_count: number; fits: boolean; shape: Shape; created: string | null; counts: Counts;
    orientation: Orientation;
  };
  busy: "scan" | "effect" | "leds" | null;
  leds: string | null;
  effect: string | null;
}

/** Which way the map faces: a tree's front (the solved angle that faces the room), or a
 * flat layout mirrored, then turned anticlockwise in quarter turns. */
export type Orientation = { front_deg: number } | { rotate_deg: 0 | 90 | 180 | 270; mirror: boolean };

/** GET /map: the current map, for the review screen. */
export interface MapInfo {
  shape: Shape;
  led_count: number;
  created: string | null;
  rounds: number | null;
  counts: Counts;
  orientation: Orientation;
  led_status: string; // one letter per LED: o ok, i interpolated, f failed
  ignored: number[]; // LEDs whose readings are ignored (filled from their neighbours)
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
  waiting: boolean; // between rounds, showing the result until scanNext()
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

/** The server's own endpoints, before a device is picked. */
export function serverApi(server: string) {
  const api = new Api(server, "");
  return {
    info: () => api.call<ServerInfo>("GET", "/info", undefined, true),
    devices: () => api.call<{ devices: DeviceSummary[] }>("GET", "/devices", undefined, true),
  };
}

export class Api {
  readonly root: string;
  readonly base: string;
  private extra: Record<string, string>;

  constructor(readonly server: string, readonly device: string) {
    this.root = server + "/api/v2";
    this.base = `${this.root}/devices/${encodeURIComponent(device)}`;
    this.extra = needsAddressSpace(server) ? { targetAddressSpace: "local" } : {};
  }

  async call<T>(method: string, path: string, body?: unknown | ArrayBuffer, root = false): Promise<T> {
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
      res = await fetch((root ? this.root : this.base) + path, init);
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

  /** The device (and everything its LEDs are doing). */
  info = () => this.call<Info>("GET", "");
  leds = (cmd: Record<string, unknown>) => this.call<{ mode: string; seconds?: number }>("POST", "/leds", cmd);
  /** `add` keeps the rounds so far and adds to them (to scan parts again). */
  scanStart = (settings: { shape: Shape; rounds?: number; camera?: string; add?: boolean }) =>
    this.call<{ id: number }>("POST", "/scan/start", settings);
  scanStop = () => this.call<{ stopping: boolean }>("POST", "/scan/stop", {});
  scanState = () => this.call<ScanState>("GET", "/scan/state");
  frames = (batch: ArrayBuffer) => this.call<{ frames: number }>("POST", "/scan/frames", batch);
  /** How many LEDs the frames taken at `since` or later show (median per frame). */
  exposureProbe = (since: number, frames = 6) =>
    this.call<{ frames: number; leds: number; lit: number }>("POST", "/scan/exposure-probe", { since, frames });
  /** Start the next round (the user is in place), or finish the scan here. */
  scanNext = (finish = false) => this.call<{ round: number }>("POST", "/scan/next", { finish });
  cameraReady = (body: { message: string; settings: Record<string, unknown> }) =>
    this.call<{ ok: boolean }>("POST", "/scan/camera-ready", body);
  play = (effect: string, params: Record<string, unknown> = {}) =>
    this.call<unknown>("POST", "/play", { effect, params });
  map = () => this.call<MapInfo>("GET", "/map");
  setOrientation = (o: Orientation) => this.call<MapInfo>("POST", "/map/orientation", o);
  /** Ignore an LED's readings (it's in the wrong place), or use them again. Answers once
   * the map is solved again, which can take a while. */
  interpolate = (index: number, interpolate: boolean) =>
    this.call<MapInfo>("POST", "/map/interpolate", { index, interpolate });
}
