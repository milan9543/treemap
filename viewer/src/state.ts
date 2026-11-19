// State shared by the scene and the panels, and the events that announce changes.
import type { CompareData, EngineState, JobState, ServerConfig, Tree, TreeMapData } from "./types";
import { Emitter } from "./util";

export const LED_JOBS = ["scan"]; // jobs that light the LEDs; effects wait meanwhile

export const state = {
  serverConfig: null as ServerConfig | null,
  tree: null as Tree | null,
  map: null as TreeMapData | null,
  compare: null as CompareData | null, // sim only: the map aligned onto the truth
  engine: { running: null, params: null, brightness: 0.8 } as EngineState,
  job: { id: 0, kind: null, status: "idle" } as JobState,
  selectedLed: null as number | null,
  scanners: 0, // scans waiting for the phone's photos
};

export const jobActive = () => state.job.status === "running";
export const ledsBusy = () => jobActive() && LED_JOBS.includes(state.job.kind ?? "");
export const mapStatus = (i: number) => state.map?.status?.[i] ?? null;

export const events = new Emitter<{
  data: void; // tree and/or map (re)loaded
  engine: EngineState;
  job: JobState;
  select: number | null;
}>();
