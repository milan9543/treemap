// Favourite effects with their settings, kept in this browser's localStorage.
import type { EffectInfo } from "./types";

export interface Favourite {
  id: string;
  name: string;
  effect: string; // effect name
  params: Record<string, unknown>; // as the engine reports them (colours as #rrggbb)
}

const KEY = "treemap.favourites";

function load(): Favourite[] {
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
  list = $state<Favourite[]>(load());
  lastPlayed = $state<string | null>(null); // the favourite last started, to offer updating it

  constructor() {
    // Another tab changed them: pick that up.
    try {
      window.addEventListener("storage", (e) => { if (e.key === KEY) this.list = load(); });
    } catch { /* no window */ }
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
    this.persist();
    return fav;
  }

  rename(id: string, name: string): void {
    const trimmed = name.trim();
    if (!trimmed) return;
    this.list = this.list.map((f) => (f.id === id ? { ...f, name: trimmed } : f));
    this.persist();
  }

  update(id: string, params: Record<string, unknown>): void {
    this.list = this.list.map((f) => (f.id === id ? { ...f, params: { ...params } } : f));
    this.persist();
  }

  remove(id: string): void {
    this.list = this.list.filter((f) => f.id !== id);
    this.persist();
  }

  private persist(): void {
    try { localStorage.setItem(KEY, JSON.stringify(this.list)); } catch { /* unavailable */ }
  }
}

export const favourites = new Favourites();
