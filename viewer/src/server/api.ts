// `treemap serve`'s API (treemap/api/app.py and device.py), from the server's own page:
// same origin, so no CORS and no local-network permission.

export const API_VERSION = 2;
const BASE = "/api/v2";

export type Params = Record<string, unknown>;
export type Counts = { ok: number; interpolated: number; failed: number };
export type Orientation = { front_deg: number } | { rotate_deg: number; mirror: boolean };

export interface Info {
  api: number;
  server: string;
  url: string | null; // the server on the LAN, for the phone
  scan_page: string;
  devices: number;
}

export interface Device {
  id: string;
  name: string;
  host: string;
  virtual: boolean;
  led_count: number | null; // null until its WLED has answered once
  status: {
    alive: boolean | null; // null: not asked yet
    checked_s_ago: number | null;
    wled: { name: string; version: string | null; led_count: number } | null;
    error: string | null;
  };
  // once its LED count is known:
  shape?: "tree" | "flat";
  map?: null | { led_count: number; fits: boolean; shape: "tree" | "flat"; created: string | null;
    counts: Counts; orientation: Orientation };
  legacy_map?: boolean; // a map from before devices fits it
  busy?: "scan" | "effect" | "leds" | null;
  effect?: string | null;
  send?: boolean; // frames go to the controller (else to this page only)
  gamma?: number;
  timing?: Timing; // the effects engine's last 2 s
  error?: string | null; // why the controller's output can't be opened
}

type Ms = { median: number; max: number };
export interface Timing {
  fps_target: number;
  fps: number | null; // null while nothing plays (then the rest are null too)
  render_ms: Ms | null;
  send_ms: Ms | null;
  gap_ms: Ms | null; // from one frame's start to the next
  late: number;
  slow: boolean;
}

export interface MapInfo {
  shape: "tree" | "flat";
  led_count: number;
  created: string | null;
  counts: Counts;
  orientation: Orientation;
  led_status: string; // o ok, i interpolated, f failed
  positions: ([number, number, number] | null)[]; // y up, 0-1 from the lowest LED
}

export interface EffectParam {
  name: string;
  kind: "color" | "float" | "int" | "choice" | "bool";
  default: unknown;
  label: string;
  help: string;
  min: number | null;
  max: number | null;
  step: number | null;
  choices: string[];
}

export interface EffectInfo {
  name: string;
  label: string;
  group: string;
  description: string;
  needs_map: boolean;
  params: EffectParam[];
}

export interface Playing {
  effect: string | null;
  params: Params | null;
  brightness: number;
  error: string | null;
  favourite: string | null;
  playlist: null | { id: string; name: string; item: number; next_s: number };
}

export interface Favourite { id: string; name: string; effect: string; params: Params }
export interface PlaylistItem { favourite: string; duration_s: number }
export interface Playlist { id: string; name: string; items: PlaylistItem[]; crossfade_s: number; shuffle: boolean }
export type PlaylistFields = Omit<Playlist, "id">;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, cache: "no-store" };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  let res: Response;
  try {
    res = await fetch(BASE + path, init);
  } catch {
    throw new ApiError(0, "Can't reach the server: is `treemap serve` still running?");
  }
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* empty */
  }
  if (!res.ok) throw new ApiError(res.status, (data as { error?: string } | null)?.error ?? `HTTP ${res.status}`);
  return data as T;
}

const enc = encodeURIComponent;

export const api = {
  info: () => call<Info>("GET", "/info"),
  devices: () => call<{ devices: Device[] }>("GET", "/devices"),
  addDevice: (body: { host: string; name?: string; led_count?: number }) => call<Device>("POST", "/devices", body),
  effects: () => call<{ effects: EffectInfo[] }>("GET", "/effects"),
  favourites: () => call<{ favourites: Favourite[] }>("GET", "/favourites"),
  addFavourite: (f: Omit<Favourite, "id">) => call<Favourite>("POST", "/favourites", f),
  updateFavourite: (id: string, change: { name?: string; params?: Params }) =>
    call<Favourite>("PUT", `/favourites/${enc(id)}`, change),
  deleteFavourite: (id: string) => call<unknown>("DELETE", `/favourites/${enc(id)}`),
  playlists: () => call<{ playlists: Playlist[] }>("GET", "/playlists"),
  addPlaylist: (p: PlaylistFields) => call<Playlist>("POST", "/playlists", p),
  putPlaylist: (id: string, p: PlaylistFields) => call<Playlist>("PUT", `/playlists/${enc(id)}`, p),
  deletePlaylist: (id: string) => call<unknown>("DELETE", `/playlists/${enc(id)}`),
};

/** One device's endpoints. */
export function deviceApi(id: string) {
  const d = `/devices/${enc(id)}`;
  return {
    get: () => call<Device>("GET", d),
    update: (change: { name?: string; led_count?: number }) => call<Device>("PUT", d, change),
    remove: () => call<unknown>("DELETE", d),
    map: () => call<MapInfo>("GET", `${d}/map`),
    adoptMap: () => call<MapInfo>("POST", `${d}/map/adopt`, {}),
    frame: () => call<{ seq: number; rgb: string }>("GET", `${d}/frame`),
    setSend: (on: boolean) => call<{ send: boolean }>("POST", `${d}/send`, { on }),
    leds: (cmd: Record<string, unknown>) => call<unknown>("POST", `${d}/leds`, cmd),
    playing: () => call<Playing>("GET", `${d}/play`),
    play: (effect: string, params: Params = {}) => call<Playing>("POST", `${d}/play`, { effect, params }),
    playFavourite: (fav: string) => call<Playing>("POST", `${d}/play`, { favourite: fav }),
    playPlaylist: (pl: string) => call<Playing>("POST", `${d}/play`, { playlist: pl }),
    playNext: () => call<Playing>("POST", `${d}/play/next`, {}),
    setParams: (params: Params) => call<Playing>("POST", `${d}/play/params`, { params }),
    setBrightness: (brightness: number) => call<Playing>("POST", `${d}/brightness`, { brightness }),
    stop: () => call<Playing>("POST", `${d}/stop`, {}),
  };
}
export type DeviceApi = ReturnType<typeof deviceApi>;

/** The scan page's address for this device, for the phone (the QR code). */
export function scanLink(info: Info, device: Device): string {
  const server = info.url ?? location.origin;
  const u = new URL(info.scan_page);
  u.searchParams.set("server", server);
  u.searchParams.set("device", device.id);
  return u.toString();
}
