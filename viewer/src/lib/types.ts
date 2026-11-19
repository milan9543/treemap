// Data from the Python server (see treemap/sim/server.py).

export type Vec3 = [number, number, number];

export interface StripSpec { leds: number; length: number | null; start: string }
export interface TreeSpec {
  strips: StripSpec[];
  height: number | null;
  radius: number | null;
  layout: string;
  quirks: boolean;
  seed: number | null;
}

export interface Strand {
  start: number;
  count: number;
  spacing: number;
  turns: number;
  index_from_top: boolean;
}

export interface Tree {
  version: number;
  seed: number;
  led_count: number;
  height: number;
  radius: number;
  trunk_radius: number;
  layout: string;
  strands: Strand[];
  positions: Vec3[];
  spec?: TreeSpec;
  warnings?: string[];
  branches?: Branch[];
}

/** A branch of the simulated tree: level 0 main branch (or leader), 1 side branchlet,
 *  2 twig holding an LED. Points run from its base out to its tip. */
export interface Branch {
  level: number;
  radius: [number, number];
  points: Vec3[];
}

export type Status = "ok" | "interpolated" | "failed";

export interface TreeMapData {
  positions: (Vec3 | null)[];
  status: Status[];
  counts?: Record<Status, number>;
  created?: string;
  views?: number[];
  outliers?: number[];
  forced_interpolate?: number[];
  rounds?: number;
}

export interface ServerConfig {
  led_count: number;
  defaults: TreeSpec;
  limits: Record<string, [number, number]>;
  random: Record<string, [number, number]>;
  jobs: boolean;
  config?: {
    camera: { type: string; fov_deg: number };
    scan: { profile: string; camera_fps: number; round_s: number; status_s: number };
    [key: string]: unknown;
  };
  config_source?: string | null;
  hidden_leds?: number[];
}

export interface EffectParam {
  name: string;
  label: string;
  kind: "float" | "int" | "bool" | "color" | "choice";
  default: unknown;
  min?: number;
  max?: number;
  step?: number;
  choices?: string[];
  help?: string;
}
export interface EffectInfo {
  name: string;
  label: string;
  group: string;
  description: string;
  params: EffectParam[];
}
export interface EffectsInfo { available: boolean; output: string; effects: EffectInfo[] }

export interface EngineState {
  running: string | null;
  params: Record<string, unknown> | null;
  brightness: number;
  map?: MapChoice | null; // positions the 3D effects use
  maps?: MapChoice[];
  error?: string | null;
}
export type MapChoice = "scanned" | "truth";

export interface ScanProgress {
  round: number;
  rounds_saved: number;
  phase: "flashing" | "solving" | "status";
  remaining?: number;
  frames?: number;
  identified?: number;
  counts?: Record<Status, number> | null;
  message?: string;
}

export interface JobState {
  id: number;
  kind: string | null;
  status: "idle" | "running" | "done" | "error" | "cancelled";
  params?: Record<string, unknown>;
  message?: string;
  progress?: ScanProgress | null;
  result?: any;
  error?: string | null;
}

/** /api/compare: the map aligned onto the simulated tree (metres) and each LED's error. */
export interface CompareData {
  positions: (Vec3 | null)[];
  errors_m: (number | null)[];
  status: Status[];
  height_m: number;
  rotation_deg: number;
  scale: number;
  rows: { status: string; count: number; median: number; p95: number }[];
}

export interface Detections { size: [number, number]; blobs: [number, number, number][] }
