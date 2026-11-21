// Everything the UI shows, as Svelte runes: data from the server, and UI state. The 3D
// code (src/3d) reads and writes it too.
import type {
  CompareData, Detections, EffectsInfo, EngineState, JobState, ServerConfig, Tree, TreeMapData,
} from "./types";

export type Step = "tree" | "scan" | "map" | "effects";
export type ViewMode = "truth" | "scan" | "compare";
export type Layer = "off" | "cone" | "branch" | "wire";
export type EffectsTab = "favourites" | "3d" | "simple";

function saved<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(`treemap.${key}`);
    return v === null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}

export function save(key: string, value: unknown): void {
  try { localStorage.setItem(`treemap.${key}`, JSON.stringify(value)); } catch { /* unavailable */ }
}

class App {
  // -- from the server
  connected = $state(false);
  config = $state.raw<ServerConfig | null>(null);
  effects = $state.raw<EffectsInfo | null>(null);
  tree = $state.raw<Tree | null>(null);
  map = $state.raw<TreeMapData | null>(null);
  compare = $state.raw<CompareData | null>(null); // simulator: the map aligned onto the truth
  engine = $state.raw<EngineState>({ running: null, params: null, brightness: 0.8 });
  job = $state.raw<JobState>({ id: 0, kind: null, status: "idle" });
  jobError = $state<{ kind: string | null; error: string } | null>(null); // a refused job.start
  effectError = $state<string | null>(null);
  producers = $state(0); // programs sending LED colours
  sources = $state.raw<string[]>([]);
  scanners = $state(0); // scans listening to the phone
  ledFps = $state(0);
  frameLeds = $state<number | null>(null); // LEDs per frame the server sends
  detections = $state.raw<Detections | null>(null);
  detectionsAt = $state(0);
  loaded = $state(false);

  // -- UI
  step = $state<Step>(saved("step", "scan"));
  sidebar = $state(saved("sidebar", true));
  settings = $state(false);
  viewMode = $state<ViewMode>("truth");
  effectsTab = $state<EffectsTab>(saved("effectsTab", "3d"));
  layers = $state<Record<Layer, boolean>>(saved("layers", { off: true, cone: false, branch: true, wire: false }));
  selectedLed = $state<number | null>(null);
  walking = $state(false);
  locked = $state(false); // pointer captured for mouse look
  phoneFps = $state(0);
  hover = $state<{ x: number; y: number; text: string } | null>(null);

  get sim(): boolean {
    return (this.config?.config?.camera.type ?? "sim") === "sim";
  }
  get jobActive(): boolean {
    return this.job.status === "running";
  }
  get scanning(): boolean {
    return this.jobActive && this.job.kind === "scan";
  }
  get jobsAvailable(): boolean {
    return !!this.config?.jobs;
  }
}

export const app = new App();

export const STEPS: { id: Step; label: string; key: string }[] = [
  { id: "tree", label: "Tree", key: "1" },
  { id: "scan", label: "Scan", key: "2" },
  { id: "map", label: "Map", key: "3" },
  { id: "effects", label: "Effects", key: "4" },
];

export function setStep(step: Step): void {
  app.step = step;
  app.sidebar = true;
  save("step", step);
}

export const mapStatus = (i: number) => app.map?.status?.[i] ?? null;
