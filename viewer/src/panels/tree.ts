// The Tree panel: set up the strips and size of the simulated tree, then Generate.
import { state } from "../state";
import type { StripSpec, TreeSpec } from "../types";
import { $, collapsible } from "../util";
import { NOT_CONNECTED, request, connected } from "../ws";

const LIMITS_FALLBACK: Record<string, [number, number]> = {
  leds: [1, 2000], strips: [1, 8], total_leds: [1, 5000], spacing: [0.01, 0.5],
};
const limits = () => state.serverConfig?.limits ?? LIMITS_FALLBACK;
let formFilled = false;

function stripRow(strip: StripSpec): HTMLTableRowElement {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td class="num"></td>
    <td><input type="number" class="leds" min="1" step="1" title="Number of LEDs on this strip"></td>
    <td><input type="number" class="length" min="0.1" step="0.1" placeholder="random" title="Metres of strip; blank = random 6.5–8 cm spacing"></td>
    <td class="spacing"></td>
    <td><select class="start" title="Which end of the strip is index 0">
      <option value="auto">auto</option><option value="bottom">bottom</option><option value="top">top</option>
    </select></td>
    <td><button class="icon remove" title="Remove this strip" aria-label="Remove strip">×</button></td>`;
  tr.querySelector<HTMLInputElement>(".leds")!.value = String(strip.leds);
  tr.querySelector<HTMLInputElement>(".length")!.value = strip.length === null ? "" : String(strip.length);
  tr.querySelector<HTMLSelectElement>(".start")!.value = strip.start || "auto";
  tr.querySelector<HTMLButtonElement>(".remove")!.onclick = () => { tr.remove(); refreshForm(); };
  tr.querySelectorAll("input, select").forEach((el) => el.addEventListener("input", refreshForm));
  return tr;
}

function rows(): HTMLTableRowElement[] {
  return [...$("strips").children] as HTMLTableRowElement[];
}

function readStrips(): StripSpec[] {
  return rows().map((tr) => {
    const leds = parseInt(tr.querySelector<HTMLInputElement>(".leds")!.value, 10);
    const lenText = tr.querySelector<HTMLInputElement>(".length")!.value.trim();
    return { leds, length: lenText === "" ? null : parseFloat(lenText), start: tr.querySelector<HTMLSelectElement>(".start")!.value };
  });
}

function refreshForm(): void {
  const strips = readStrips();
  const [smin, smax] = limits().spacing;
  rows().forEach((tr, i) => {
    tr.querySelector(".num")!.textContent = String(i + 1);
    tr.querySelector<HTMLButtonElement>(".remove")!.disabled = strips.length <= 1;
    const s = strips[i], cell = tr.querySelector<HTMLElement>(".spacing")!;
    if (!Number.isFinite(s.leds) || s.leds < 1) { cell.textContent = "–"; cell.classList.add("bad"); return; }
    if (s.length === null) { cell.textContent = "random"; cell.classList.remove("bad"); return; }
    const sp = s.length / s.leds;
    cell.textContent = Number.isFinite(sp) ? `${(sp * 100).toFixed(1)} cm` : "–";
    cell.classList.toggle("bad", !(sp >= smin && sp <= smax));
    cell.title = cell.classList.contains("bad") ? `spacing must be ${smin * 100}–${smax * 100} cm` : "";
  });
  $<HTMLButtonElement>("add-strip").disabled = strips.length >= limits().strips[1];
  const total = strips.reduce((a, s) => a + (Number.isFinite(s.leds) ? s.leds : 0), 0);
  const cfgCount = state.serverConfig ? state.serverConfig.led_count : null;
  const t = $("total");
  t.textContent = `${total} LEDs` + (cfgCount !== null && cfgCount !== total ? ` · config has ${cfgCount}` : "");
  t.classList.toggle("warn", cfgCount !== null && cfgCount !== total);
  t.title = t.classList.contains("warn")
    ? `led_count in config.yaml is ${cfgCount}: test patterns and effects will drive ${cfgCount} LEDs` : "";
}

function fillForm(spec: TreeSpec): void {
  const body = $("strips");
  body.innerHTML = "";
  (spec.strips || []).forEach((s) => body.appendChild(stripRow(s)));
  $<HTMLInputElement>("g-height").value = spec.height === null ? "" : String(spec.height);
  $<HTMLInputElement>("g-radius").value = spec.radius === null ? "" : String(spec.radius);
  $<HTMLSelectElement>("g-layout").value = spec.layout || "auto";
  $<HTMLInputElement>("g-quirks").checked = spec.quirks !== false;
  $<HTMLInputElement>("g-seed").value = ""; // blank = a new random tree each time
  refreshForm();
  updatePlaceholders();
}

function updatePlaceholders(): void {
  const rnd = state.serverConfig?.random;
  const tree = state.tree;
  const fmt = (r?: [number, number]) => (r ? `random ${r[0]}–${r[1]}` : "random");
  $<HTMLInputElement>("g-height").placeholder = tree ? `random (now ${tree.height.toFixed(2)})` : fmt(rnd?.height);
  $<HTMLInputElement>("g-radius").placeholder = tree ? `random (now ${tree.radius.toFixed(2)})` : fmt(rnd?.radius);
  $<HTMLInputElement>("g-seed").placeholder = tree ? `random (now ${tree.seed})` : "random";
}

function setStatus(text: string, kind = ""): void {
  const s = $("g-status");
  s.textContent = text;
  s.className = kind;
}

function num(id: string): number | null {
  const v = $<HTMLInputElement>(id).value.trim();
  return v === "" ? null : Number(v);
}

async function generate(): Promise<void> {
  const strips = readStrips();
  if (strips.some((s) => !Number.isInteger(s.leds) || s.leds < 1)) {
    setStatus("Every strip needs a whole number of LEDs.", "bad");
    return;
  }
  const spec = {
    strips, height: num("g-height"), radius: num("g-radius"),
    layout: $<HTMLSelectElement>("g-layout").value, quirks: $<HTMLInputElement>("g-quirks").checked,
    seed: num("g-seed"),
  };
  if (!connected()) { setStatus(NOT_CONNECTED, "bad"); return; }
  const btn = $<HTMLButtonElement>("generate");
  btn.disabled = true;
  setStatus("Generating…");
  const reply = await request("generate", "generated", { spec });
  btn.disabled = false;
  if (reply.ok) {
    setStatus(`Generated seed ${reply.seed}: ${reply.led_count} LEDs.` +
      (reply.warnings.length ? " See the warnings below." : ""), reply.warnings.length ? "warn" : "");
  } else {
    setStatus(reply.error, "bad");
  }
}

/** After the tree or config (re)loads. */
export function refreshTreePanel(): void {
  if (!formFilled) {
    if (state.tree?.spec) fillForm(state.tree.spec);
    else if (state.serverConfig) fillForm(state.serverConfig.defaults);
    formFilled = !!(state.tree || state.serverConfig);
  }
  const ul = $("g-warnings");
  ul.innerHTML = "";
  for (const w of state.tree?.warnings ?? []) {
    const li = document.createElement("li");
    li.textContent = w;
    ul.appendChild(li);
  }
  updatePlaceholders();
}

export function setupTreePanel(): void {
  $("add-strip").onclick = () => {
    const strips = readStrips();
    const last = strips[strips.length - 1] || { leds: 200, length: null, start: "auto" };
    $("strips").appendChild(stripRow({ ...last, start: "auto" }));
    refreshForm();
  };
  $("generate").onclick = generate;
  $("g-defaults").onclick = () => {
    if (state.serverConfig) fillForm(state.serverConfig.defaults);
    setStatus("");
  };
  $("gen").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.target as HTMLElement).matches("input") && !$<HTMLButtonElement>("generate").disabled) generate();
  });
  collapsible("gen");
}
