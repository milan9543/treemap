// Loading from the server, reacting to its messages, and the actions the UI triggers.
import * as controls from "../3d/controls";
import * as scene from "../3d/scene";
import { app, setStep, type ViewMode } from "./state.svelte";
import type { CompareData, EffectsInfo, MapChoice, ServerConfig, Tree, TreeMapData } from "./types";
import { fetchJson, throttled } from "./util";
import * as ws from "./ws";

// -- data --------------------------------------------------------------------------------

export async function loadAll(): Promise<void> {
  const [tree, map] = await Promise.all([fetchJson<Tree>("/api/tree"), fetchJson<TreeMapData>("/api/map")]);
  app.tree = tree && tree.version === 3 ? tree : null; // old format: wait for a regenerate
  app.map = map;
  app.compare = app.tree && map ? await fetchJson<CompareData>("/api/compare") : null;
  scene.setData();
  scene.rebuild();
  controls.treeChanged();
  app.loaded = true;
}

export async function start(): Promise<void> {
  const [config, effects] = await Promise.all([
    fetchJson<ServerConfig>("/api/config"),
    fetchJson<EffectsInfo>("/api/effects"),
  ]);
  app.config = config;
  app.effects = effects;
  if (!app.sim && app.step === "tree") setStep("scan");
  await loadAll();
  ws.connect();
}

let frames = 0;
setInterval(() => { app.ledFps = frames; frames = 0; }, 1000);

ws.onLedFrame((buf) => { frames++; scene.applyFrame(buf); });
ws.on("reload", () => loadAll());
ws.on("status", (msg) => {
  app.producers = msg.producers;
  app.sources = msg.sources ?? [];
  app.scanners = msg.scanners ?? 0;
});
ws.on("engine", (msg) => {
  app.engine = msg;
  app.effectError = msg.error ?? null;
});
ws.on("effect.error", (msg) => { app.effectError = msg.error; });
ws.on("job", (msg) => {
  const was = app.job;
  app.job = msg;
  if (msg.id !== was.id) app.jobError = null;
});
ws.on("job.rejected", (msg) => { app.jobError = { kind: pendingJob, error: msg.error }; });
ws.on("scan.detections", (msg) => {
  app.detections = msg;
  app.detectionsAt = performance.now();
});

// -- view --------------------------------------------------------------------------------

export function setViewMode(m: ViewMode): void {
  if (!scene.modeAvailable(m) || m === app.viewMode) return;
  app.viewMode = m;
  scene.rebuild();
}

export function cycleViewMode(): void {
  const modes: ViewMode[] = ["truth", "scan", "compare"];
  const k = modes.indexOf(app.viewMode);
  for (let d = 1; d < modes.length; d++) {
    const m = modes[(k + d) % modes.length];
    if (scene.modeAvailable(m)) return setViewMode(m);
  }
}

// -- jobs --------------------------------------------------------------------------------

let pendingJob: string | null = null;

export function startJob(kind: string, params: Record<string, unknown> = {}): void {
  pendingJob = kind;
  app.jobError = null;
  if (!ws.send({ type: "job.start", job: kind, params })) {
    app.jobError = { kind, error: ws.NOT_CONNECTED };
  }
}

export const cancelJob = () => ws.send({ type: "job.cancel" });

/** Scans start over: the server forgets earlier rounds. */
export function startScan(): void {
  startJob("scan");
  if (app.sim) controls.setWalking(true);
}

// -- effects -----------------------------------------------------------------------------

const remembered: Record<string, Record<string, unknown>> = {}; // last params per effect

function send(msg: object): boolean {
  if (ws.send(msg)) return true;
  app.effectError = ws.NOT_CONNECTED;
  return false;
}

export function runEffect(name: string, params?: Record<string, unknown>): void {
  const fitted = fitParams(name, params ?? remembered[name] ?? {});
  if (send({ type: "effect.run", effect: name, params: fitted })) app.effectError = null;
}

/** Drop settings the effect no longer has (or no longer accepts, e.g. a colour that's
 *  now a choice of Christmas colours), so a favourite saved by an older version still
 *  plays, with defaults for what changed. */
function fitParams(name: string, params: Record<string, unknown>): Record<string, unknown> {
  const fx = app.effects?.effects.find((e) => e.name === name);
  if (!fx) return params;
  const byName = new Map(fx.params.map((p) => [p.name, p]));
  return Object.fromEntries(Object.entries(params).filter(([k, v]) => {
    const p = byName.get(k);
    return !!p && (p.kind !== "choice" || (p.choices ?? []).includes(v as string));
  }));
}

export const stopEffect = () => send({ type: "effect.stop" });

const sendParams = throttled(60, (params: Record<string, unknown>) => send({ type: "effect.params", params }));

export function setEffectParam(name: string, value: unknown): void {
  const running = app.engine.running;
  if (!running) return;
  remembered[running] = { ...(remembered[running] ?? app.engine.params ?? {}), [name]: value };
  sendParams({ [name]: value });
}

export const setBrightness = throttled(60, (value: number) => send({ type: "effect.brightness", value }));

export function setEffectMap(map: MapChoice): void {
  if (send({ type: "effect.map", map })) app.effectError = null;
}

// -- LEDs --------------------------------------------------------------------------------

const HIGHLIGHT = { color: "#0050ff", neighbours: true };

/** Select an LED: show it in the Map step's inspector and light it blue. */
export function selectLed(i: number | null): void {
  app.selectedLed = i;
  if (i === null) return;
  if (app.step !== "map") setStep("map");
  if (!app.scanning) runEffect("led", { index: i, ...HIGHLIGHT });
}

// -- tree --------------------------------------------------------------------------------

export function generate(spec: object): Promise<{ ok: boolean; error?: string; seed?: number; led_count?: number; warnings?: string[] }> {
  return ws.request("generate", "generated", { spec });
}
