// The Effects panel: pick an effect, tune its parameters, set the brightness.
import { events, state } from "../state";
import type { EffectInfo, EffectParam, EffectsInfo, EngineState } from "../types";
import { $, collapsible, throttled } from "../util";
import { NOT_CONNECTED, on, send as wsSend } from "../ws";

let effects: EffectInfo[] = [];
const remembered: Record<string, Record<string, unknown>> = {}; // last params per effect
let shownParamsFor: string | null = null; // effect whose controls are built

export function fxStatus(text: string, kind = ""): void {
  const s = $("fx-status");
  s.textContent = text;
  s.className = kind;
}

/** Send, reporting a lost connection in the Effects panel. */
export function send(msg: object): boolean {
  if (wsSend(msg)) return true;
  fxStatus(NOT_CONNECTED, "bad");
  return false;
}

export function runEffect(name: string, params?: Record<string, unknown>): void {
  if (send({ type: "effect.run", effect: name, params: params ?? remembered[name] ?? {} })) fxStatus("");
}

const sendParams = throttled(60, (params: Record<string, unknown>) => send({ type: "effect.params", params }));
const sendBrightness = throttled(60, (value: number) => send({ type: "effect.brightness", value }));

const fmt = (p: EffectParam, v: unknown) =>
  p.kind === "int" ? String(v) : (+(v as number)).toFixed(p.step && p.step < 0.1 ? 2 : 1);

function paramControl(p: EffectParam, value: unknown): HTMLElement {
  const row = document.createElement("label");
  row.className = "ctl";
  row.title = p.help || "";
  const name = document.createElement("span");
  name.textContent = p.label;
  const out = document.createElement("output");
  const changed = (v: unknown) => {
    const running = state.engine.running!;
    remembered[running] = { ...(remembered[running] || {}), [p.name]: v };
    sendParams({ [p.name]: v });
  };
  let input: HTMLInputElement | HTMLSelectElement;
  if (p.kind === "color") {
    const i = document.createElement("input");
    i.type = "color";
    i.value = String(value);
    i.oninput = () => changed(i.value);
    input = i;
  } else if (p.kind === "bool") {
    const i = document.createElement("input");
    i.type = "checkbox";
    i.checked = !!value;
    i.onchange = () => changed(i.checked);
    input = i;
  } else if (p.kind === "choice") {
    const sel = document.createElement("select");
    (p.choices ?? []).forEach((c) => sel.add(new Option(c, c)));
    sel.value = String(value);
    sel.onchange = () => changed(sel.value);
    input = sel;
  } else {
    const i = document.createElement("input");
    i.type = "range";
    i.min = String(p.min);
    i.max = String(p.max);
    i.step = p.step !== undefined ? String(p.step) : p.kind === "int" ? "1" : "any";
    i.value = String(value);
    out.textContent = fmt(p, value);
    i.oninput = () => {
      const v = p.kind === "int" ? parseInt(i.value, 10) : parseFloat(i.value);
      out.textContent = fmt(p, v);
      changed(v);
    };
    input = i;
  }
  input.dataset.param = p.name;
  input.setAttribute("aria-label", p.label);
  row.append(name, input, out);
  return row;
}

function syncControl(input: HTMLInputElement, p: EffectParam, value: unknown): void {
  if (document.activeElement === input) return; // don't fight the user's drag
  if (p.kind === "bool") input.checked = !!value;
  else input.value = String(value);
  const out = input.parentElement!.querySelector("output");
  if (out && input.type === "range") out.textContent = fmt(p, value);
}

export function buildEffects(info: EffectsInfo | null): void {
  effects = info?.effects ?? [];
  const list = $("fx-list");
  list.innerHTML = "";
  if (!info || !info.available) {
    list.innerHTML = '<div class="muted">Effects aren\'t available from this server.</div>';
    return;
  }
  $("fx-out").textContent = `→ ${info.output}`;
  // The Mapping effects live in their own panel.
  const groups = [...new Set(effects.map((e) => e.group))].filter((g) => g !== "Mapping");
  for (const g of groups) {
    const head = document.createElement("div");
    head.className = "section";
    head.textContent = g;
    const chips = document.createElement("div");
    chips.className = "chips";
    effects.filter((e) => e.group === g).forEach((e) => {
      const b = document.createElement("button");
      b.textContent = e.label;
      b.title = e.description;
      b.dataset.effect = e.name;
      b.onclick = () => runEffect(e.name);
      chips.appendChild(b);
    });
    list.append(head, chips);
  }
}

function onEngineState(st: EngineState): void {
  state.engine = st;
  document.querySelectorAll<HTMLButtonElement>("#fx-list button").forEach((b) =>
    b.classList.toggle("running", b.dataset.effect === st.running));
  const desc = effects.find((e) => e.name === st.running);
  $("fx-desc").textContent = desc ? desc.description : "";
  const box = $("fx-params");
  const params = st.params ?? {};
  if (!desc) {
    box.innerHTML = "";
    shownParamsFor = null;
  } else if (shownParamsFor !== st.running) {
    box.innerHTML = "";
    desc.params.forEach((p) => box.appendChild(paramControl(p, params[p.name])));
    shownParamsFor = st.running;
  } else {
    desc.params.forEach((p) => {
      const input = box.querySelector<HTMLInputElement>(`[data-param="${p.name}"]`);
      if (input) syncControl(input, p, params[p.name]);
    });
  }
  if (st.running) remembered[st.running] = { ...params };
  const bright = $<HTMLInputElement>("fx-bright");
  if (document.activeElement !== bright) {
    bright.value = String(Math.round(st.brightness * 100));
    $("fx-bright-val").textContent = `${bright.value}%`;
  }
  $<HTMLButtonElement>("fx-stop").disabled = !st.running;
  events.emit("engine", st);
  if (st.error) fxStatus(st.error, "bad");
  else if (st.running) fxStatus(`Running ${desc ? desc.label : st.running}`);
  else if (!$("fx-status").classList.contains("bad")) fxStatus("Stopped");
}

export function setupEffectsPanel(): void {
  $("fx-bright").oninput = () => {
    const v = $<HTMLInputElement>("fx-bright").value;
    $("fx-bright-val").textContent = `${v}%`;
    sendBrightness(Number(v) / 100);
  };
  $("fx-stop").onclick = () => send({ type: "effect.stop" });
  $<HTMLButtonElement>("fx-stop").disabled = true;
  on("engine", onEngineState);
  on("effect.error", (msg) => fxStatus(msg.error, "bad"));
  collapsible("fx");
}
