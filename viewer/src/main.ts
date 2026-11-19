import "./style.css";
import * as controls from "./controls";
import { buildEffects, setupEffectsPanel } from "./panels/effects";
import { setupJobs } from "./panels/jobs";
import { renderMapPanel, setupMappingPanel } from "./panels/mapping";
import { setupScanPanel } from "./panels/scan";
import { refreshTreePanel, setupTreePanel } from "./panels/tree";
import { onDetections, tick as phoneTick } from "./phone";
import * as sc from "./scene";
import { events, state } from "./state";
import type { CompareData, EffectsInfo, ServerConfig, Tree, TreeMapData } from "./types";
import { $, esc, fetchJson, yamlish } from "./util";
import * as ws from "./ws";

// ---------------------------------------------------------------- data
async function loadAll(): Promise<void> {
  const [tree, map] = await Promise.all([fetchJson<Tree>("/api/tree"), fetchJson<TreeMapData>("/api/map")]);
  state.tree = tree && tree.version === 2 ? tree : null; // old format: wait for a regenerate
  state.map = map;
  state.compare = state.tree && map ? await fetchJson<CompareData>("/api/compare") : null;
  sc.setData();
  $("empty").style.display = sc.view.truthPos || sc.view.scanPos ? "none" : "flex";
  $<HTMLButtonElement>("mode-scan").disabled = !sc.view.scanPos;
  $<HTMLButtonElement>("mode-truth").disabled = !sc.view.truthPos;
  $<HTMLButtonElement>("mode-compare").disabled = !(sc.view.truthPos && state.compare);
  $("mode-compare").style.display = state.tree ? "" : "none";
  sc.rebuild();
  controls.treeChanged();
  updateInfo();
  renderMapPanel();
  refreshTreePanel();
  events.emit("data", undefined);
}

function updateInfo(): void {
  const { tree, map } = state;
  const lines: string[] = [];
  if (tree) {
    lines.push(`seed ${tree.seed} · ${tree.led_count} LEDs · ${tree.layout}`);
    lines.push(`h ${tree.height.toFixed(2)} m · r ${tree.radius.toFixed(2)} m`);
    tree.strands.forEach((s, i) => lines.push(
      `strip ${i + 1}: ${s.start}–${s.start + s.count - 1} · ${(s.spacing * 100).toFixed(1)} cm · ` +
      `${s.turns.toFixed(1)} turns${s.index_from_top ? " · from top" : ""}`));
  }
  lines.push(map ? `scanned map: ${map.positions.length} LEDs` : "scanned map: none yet");
  $("info").textContent = lines.join("\n");
  for (const m of ["truth", "scan", "compare"]) $(`mode-${m}`).classList.toggle("active", sc.view.mode === m);
  renderLegend();
}

function renderLegend(): void {
  const el = $("cmp-legend");
  const cmp = state.compare;
  el.classList.toggle("on", sc.view.mode === "compare" && !!cmp);
  if (!cmp) return;
  const cm = (f: number) => `${(f * cmp.height_m * 100).toFixed(1)} cm`;
  const rows = cmp.rows.filter((r) => r.count).map((r) =>
    `<tr><td>${r.status}</td><td class="n">${r.count}</td><td class="n">${cm(r.median)}</td><td class="n">${cm(r.p95)}</td></tr>`).join("");
  el.innerHTML = `Lines run from each LED's true position to where the scan put it.
    <div>0<span class="scale"></span>5+ cm</div>
    <table class="res"><thead><tr><th></th><th class="n">LEDs</th><th class="n">median</th><th class="n">p95</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

const MODES: sc.Mode[] = ["truth", "scan", "compare"];
const modeAvailable = (m: sc.Mode) =>
  m === "truth" ? !!sc.view.truthPos : m === "scan" ? !!sc.view.scanPos : !!(sc.view.truthPos && state.compare);

function setMode(m: sc.Mode): void {
  if (modeAvailable(m) && m !== sc.view.mode) {
    sc.view.mode = m;
    sc.rebuild();
    updateInfo();
  }
}

function nextMode(): sc.Mode {
  const k = MODES.indexOf(sc.view.mode);
  for (let d = 1; d <= MODES.length; d++) {
    const m = MODES[(k + d) % MODES.length];
    if (modeAvailable(m)) return m;
  }
  return sc.view.mode;
}

// ---------------------------------------------------------------- live status
let frameCount = 0, producers = 0;
setInterval(() => {
  $("fps").textContent = producers ? `${frameCount} fps` : "idle";
  frameCount = 0;
}, 1000);

// Two programs sending at once (e.g. a forgotten `treemap show-mapping` in a terminal
// and the viewer's effects) make the LEDs flicker between their frames.
function showSources(sources: string[]): void {
  const w = $("warn-src");
  if (sources.length < 2) { w.style.display = "none"; return; }
  w.innerHTML = `${sources.length} programs are sending colours at once, so the LEDs flicker between them:` +
    `<ul>${sources.map((s) => `<li><code>${esc(s)}</code></li>`).join("")}</ul>Stop all but one (Ctrl-C in its terminal).`;
  w.style.display = "block";
}

ws.onLedFrame((buf) => { frameCount++; sc.applyFrame(buf); });
ws.on("reload", () => loadAll());
ws.on("status", (msg) => {
  producers = msg.producers;
  state.scanners = msg.scanners ?? 0;
  showSources(msg.sources || []);
});
ws.on("scan.detections", onDetections);

// ---------------------------------------------------------------- toggles and keys
function toggle(id: string, name: "off" | "cone" | "wire" | "branch", force?: boolean): void {
  const b = $(id);
  b.classList.toggle("active", force);
  sc.setToggle(name, b.classList.contains("active"));
}
const toggles: Record<string, () => void> = {
  o: () => toggle("t-off", "off"),
  c: () => toggle("t-cone", "cone"),
  w: () => toggle("t-wire", "wire"),
  b: () => toggle("t-branch", "branch"),
};
$("mode-truth").onclick = () => setMode("truth");
$("mode-scan").onclick = () => setMode("scan");
$("mode-compare").onclick = () => setMode("compare");
$("reset").onclick = controls.resetView;
$("walk").onclick = () => controls.setWalking(!controls.walking);
$("t-off").onclick = toggles.o;
$("t-cone").onclick = toggles.c;
$("t-wire").onclick = toggles.w;
$("t-branch").onclick = toggles.b;
$("t-cfg").onclick = () => { $("cfg-view").classList.toggle("on"); $("t-cfg").classList.toggle("active"); };

// Walking shows the branches (they're what hide LEDs from the phone); back in orbit
// mode they return to how they were.
let branchesBefore = false;
controls.onWalkChange((on) => {
  if (on) {
    branchesBefore = $("t-branch").classList.contains("active");
    toggle("t-branch", "branch", true);
  } else {
    toggle("t-branch", "branch", branchesBefore);
  }
});

window.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const target = e.target as HTMLElement;
  if (target.closest && target.closest("input, select, textarea")) return; // typing in a form
  if (controls.walkKey(e, true)) return;
  if (e.key === "f") controls.setWalking(!controls.walking);
  else if (e.key === "t") setMode(nextMode());
  else if (e.key === "r") controls.resetView();
  else if (toggles[e.key] && !(controls.walking && e.key === "w")) toggles[e.key]();
});

// Hover: show LED index, strip and colour. Click (not drag) an LED: light it.
let hoverEvent: PointerEvent | null = null;
const canvas = sc.renderer.domElement;
canvas.addEventListener("pointermove", (e) => { hoverEvent = e; });
canvas.addEventListener("pointerleave", () => { hoverEvent = null; $("tip").style.display = "none"; });
let downAt: [number, number] | null = null;
canvas.addEventListener("pointerdown", (e) => { downAt = [e.clientX, e.clientY]; });
canvas.addEventListener("pointerup", (e) => {
  if (controls.walking || !downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 4) return;
  const i = sc.pickLed(e.clientX, e.clientY);
  if (i !== null) events.emit("select", i);
});

function updateHover(): void {
  const tip = $("tip");
  const i = hoverEvent && !controls.walking ? sc.pickLed(hoverEvent.clientX, hoverEvent.clientY) : null;
  if (i === null || !hoverEvent) { tip.style.display = "none"; return; }
  tip.textContent = sc.describeLed(i);
  tip.style.left = `${hoverEvent.clientX + 14}px`;
  tip.style.top = `${hoverEvent.clientY + 14}px`;
  tip.style.display = "block";
}

// For scripted checks in a headless browser.
(window as unknown as { treemap: object }).treemap = { camera: sc.camera, controls, state };

window.addEventListener("resize", sc.resize);
sc.resize();

sc.renderer.setAnimationLoop((now) => {
  controls.update();
  updateHover();
  sc.renderer.render(sc.scene, sc.camera);
  phoneTick(now);
});

// ---------------------------------------------------------------- start
setupJobs();
setupTreePanel();
setupEffectsPanel();
setupMappingPanel();
const [serverConfig, effects] = await Promise.all([
  fetchJson<ServerConfig>("/api/config"),
  fetchJson<EffectsInfo>("/api/effects"),
]);
state.serverConfig = serverConfig;
buildEffects(effects);
setupScanPanel();
if (serverConfig?.config) {
  $("cfg-view").textContent =
    `# ${serverConfig.config_source || "built-in defaults (no config.yaml)"}\n` + yamlish(serverConfig.config).trimStart();
} else {
  $("t-cfg").style.display = "none";
}
await loadAll();
ws.connect();
