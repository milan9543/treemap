// The Mapping panel: tree_map.json's quality, the Mapping effects (map-status,
// map-verify) and the single-LED highlight, all through the effects engine, so they
// light the real tree too when the output is WLED.
import { events, jobActive, ledsBusy, mapStatus, state } from "../state";
import { $, collapsible } from "../util";
import { fxStatus, runEffect, send } from "./effects";
import { startJob } from "./jobs";

const PROBLEM_CHIPS = 80;
const HIGHLIGHT = { color: "#0050ff", neighbours: true };

export function renderMapPanel(): void {
  const map = state.map;
  const has = !!(map && map.status);
  $("mp-empty").style.display = has ? "none" : "block";
  $("mp-main").style.display = has ? "block" : "none";
  $("mp-when").textContent = has && map!.created ? new Date(map!.created).toLocaleString() : "";
  $("mp-eval").innerHTML = ""; // an evaluation of the previous map is stale
  if (!has) { renderLedInfo(); return; }
  const c = map!.counts ?? { ok: 0, interpolated: 0, failed: 0 };
  $("mp-counts").innerHTML = (["ok", "interpolated", "failed"] as const).map((s) =>
    `<span title="${s}"><i class="sw ${s}"></i>${c[s] ?? 0} ${s}</span>`).join("");

  const box = $("mp-problems");
  box.innerHTML = "";
  const problems = map!.status.flatMap((s, i) => (s === "ok" ? [] : [i]));
  if (problems.length) {
    const head = document.createElement("div");
    head.className = "section";
    head.textContent = "Problem LEDs · click to light one";
    const chips = document.createElement("div");
    chips.className = "chips";
    problems.slice(0, PROBLEM_CHIPS).forEach((i) => {
      const b = document.createElement("button");
      b.textContent = String(i);
      b.className = map!.status[i];
      b.dataset.led = String(i);
      b.title = `LED ${i}: ${map!.status[i]}`;
      b.onclick = () => selectLed(i);
      chips.appendChild(b);
    });
    if (problems.length > PROBLEM_CHIPS) {
      const more = document.createElement("span");
      more.className = "muted";
      more.textContent = `+${problems.length - PROBLEM_CHIPS} more`;
      chips.appendChild(more);
    }
    box.append(head, chips);
  }
  renderLedInfo();
  syncMapButtons();
}

function renderLedInfo(): void {
  const el = $("mp-led");
  const i = state.selectedLed;
  if (i === null) { el.innerHTML = ""; return; }
  const map = state.map;
  const parts = [`<b>LED ${i}</b>`];
  const st = mapStatus(i);
  if (st && map) {
    parts.push(st);
    const views = map.views?.[i];
    if (views !== undefined) parts.push(`seen well in ${views} camera view${views === 1 ? "" : "s"}`);
    if ((map.outliers || []).includes(i)) parts.push("dropped as an outlier");
    if ((map.forced_interpolate || []).includes(i)) parts.push("interpolated on request");
  }
  let html = parts.join(" · ");
  if (state.serverConfig?.jobs && map) {
    const forced = (map.forced_interpolate || []).includes(i);
    html += `<div class="row">${forced
      ? '<button data-fix="measure" title="Use its observations again, then rebuild the map">Measure again</button>'
      : '<button data-fix="interpolate" title="Ignore its observations from now on and fill it in from its neighbours">Interpolate</button>'}
      <span class="muted">To measure it better, scan again and film that part of the tree.</span></div>`;
  }
  el.innerHTML = html;
  el.querySelectorAll<HTMLButtonElement>("[data-fix]").forEach((b) => {
    b.disabled = jobActive();
    b.onclick = () => startJob(b.dataset.fix!, { index: i });
  });
}

export function selectLed(i: number): void {
  state.selectedLed = i;
  renderLedInfo();
  if (ledsBusy()) return; // a scan is using the LEDs
  if (send({ type: "effect.run", effect: "led", params: { index: i, ...HIGHLIGHT } })) fxStatus("");
}

function syncMapButtons(): void {
  for (const id of ["mp-status", "mp-verify"]) {
    $(id).classList.toggle("running", state.engine.running === $(id).dataset.effect);
  }
  const params = state.engine.params as { index?: number } | null;
  const lit = state.engine.running === "led" && params ? params.index : null;
  document.querySelectorAll<HTMLButtonElement>("#mp-problems button").forEach((b) =>
    b.classList.toggle("running", Number(b.dataset.led) === lit));
}

function renderEval(r: any): void {
  const h = r.height_m * 100;
  const fmt = (f: number) => `${(f * 100).toFixed(2)}% · ${(f * h).toFixed(1)} cm`;
  const rows = r.rows.filter((x: any) => x.count).map((x: any) =>
    `<tr><td>${x.status}</td><td class="n">${x.count}</td><td class="n">${fmt(x.median)}</td><td class="n">${fmt(x.p95)}</td></tr>`).join("");
  $("mp-eval").innerHTML = `<div class="section">Error vs the simulated tree</div>
    <table class="res"><thead><tr><th></th><th class="n">LEDs</th><th class="n">median</th><th class="n">p95</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <div class="muted" style="font-size: 11px; margin-top: 3px">after aligning: rotated ${r.rotation_deg}°, scale ${r.scale}; % of the ${r.height_m} m LED height</div>`;
}

export function setupMappingPanel(): void {
  $("mp-status").onclick = () => runEffect("map-status");
  $("mp-verify").onclick = () => runEffect("map-verify");
  $("mp-evaluate").onclick = () => startJob("evaluate");
  collapsible("mp");
  events.on("engine", syncMapButtons);
  events.on("job", (st) => {
    $<HTMLButtonElement>("mp-evaluate").disabled = jobActive() || !state.serverConfig?.jobs;
    document.querySelectorAll<HTMLButtonElement>("#mp-led [data-fix]").forEach((b) => { b.disabled = jobActive(); });
    if (st.status === "done" && st.kind === "evaluate") renderEval(st.result);
  });
  events.on("select", (i) => { if (i !== null) selectLed(i); });
}
