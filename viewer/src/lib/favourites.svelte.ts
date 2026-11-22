// Favourite effects with their settings, kept by the server (data/library.json), so
// `treemap serve` and the phone's page share them. Changes show here at once and go to
// the server, which sends the whole list back to every viewer.
//
// Favourites used to live in this browser's localStorage: the first time the server
// sends its list, those are handed over once and the local copy is kept aside. A server
// that doesn't keep favourites (no config) never sends a list, and they stay local.
import type { EffectInfo } from "./types";
import { on, send } from "./ws";

export interface Favourite {
  id: string;
  name: string;
  effect: string; // effect name
  params: Record<string, unknown>; // as the engine reports them (colours as #rrggbb)
}

const KEY = "treemap.favourites";
const MOVED = "treemap.favourites.moved-to-server"; // the old local copy, kept just in case

function loadLocal(): Favourite[] {
  try {
    const list = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(list)
      ? list.filter((f) => f && typeof f.effect === "string" && typeof f.name === "string")
      : [];
  } catch {
    return [];
  }
}

/** Same effect and the same values for every parameter, regardless of key order. */
function sameParams(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].every((k) => JSON.stringify(a[k]) === JSON.stringify(b[k]));
}

/** "Plane · around, rainbow": the effect plus the choices and switches that differ from
 *  its defaults (numbers and colours would make names too long). */
export function defaultName(fx: EffectInfo, params: Record<string, unknown>): string {
  const bits: string[] = [];
  for (const p of fx.params) {
    const v = params[p.name];
    if (v === p.default) continue;
    if (p.kind === "choice") bits.push(String(v));
    else if (p.kind === "bool" && v === true) bits.push(p.label.toLowerCase());
  }
  return bits.length ? `${fx.label} · ${bits.join(", ")}` : fx.label;
}

class Favourites {
  list = $state<Favourite[]>(loadLocal());
  lastPlayed = $state<string | null>(null); // the favourite last started, to offer updating it
  onServer = $state(false); // the server keeps them
  error = $state<string | null>(null);

  constructor() {
    on("favourites", (msg) => this.fromServer(msg.list));
    on("favourites.error", (msg) => { this.error = msg.error; });
    // Another tab changed the local ones: pick that up.
    try {
      window.addEventListener("storage", (e) => { if (e.key === KEY && !this.onServer) this.list = loadLocal(); });
    } catch { /* no window */ }
  }

  private fromServer(list: Favourite[]): void {
    if (!this.onServer) {
      this.onServer = true;
      const local = loadLocal();
      if (local.length) {
        send({ type: "favourites.import", list: local });
        try {
          localStorage.setItem(MOVED, JSON.stringify(local));
          localStorage.removeItem(KEY);
        } catch { /* unavailable */ }
      }
    }
    this.list = list;
    this.error = null;
  }

  find(effect: string | null, params: Record<string, unknown> | null): Favourite | undefined {
    if (!effect || !params) return undefined;
    return this.list.find((f) => f.effect === effect && sameParams(f.params, params));
  }

  add(effect: string, params: Record<string, unknown>, name: string): Favourite {
    const taken = new Set(this.list.map((f) => f.name));
    let unique = name;
    for (let i = 2; taken.has(unique); i++) unique = `${name} ${i}`;
    const fav = { id: crypto.randomUUID?.() ?? String(Date.now()), name: unique, effect, params: { ...params } };
    this.list = [...this.list, fav];
    this.change({ type: "favourites.add", favourite: fav });
    return fav;
  }

  rename(id: string, name: string): void {
    const trimmed = name.trim();
    if (!trimmed) return;
    this.list = this.list.map((f) => (f.id === id ? { ...f, name: trimmed } : f));
    this.change({ type: "favourites.update", id, name: trimmed });
  }

  update(id: string, params: Record<string, unknown>): void {
    this.list = this.list.map((f) => (f.id === id ? { ...f, params: { ...params } } : f));
    this.change({ type: "favourites.update", id, params });
  }

  remove(id: string): void {
    this.list = this.list.filter((f) => f.id !== id);
    this.change({ type: "favourites.remove", id });
  }

  private change(msg: object): void {
    if (this.onServer) {
      if (!send(msg)) this.error = "Not connected: the change wasn't saved on the server.";
      return;
    }
    try { localStorage.setItem(KEY, JSON.stringify(this.list)); } catch { /* unavailable */ }
  }
}

export const favourites = new Favourites();
