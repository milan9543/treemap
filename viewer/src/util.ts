export function $<T extends HTMLElement = HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} missing from the page`);
  return el as T;
}

export const esc = (s: unknown): string =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

export async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const r = await fetch(url, { cache: "no-store" });
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    return null;
  }
}

/** At most one call per `ms`, always delivering the latest arguments last. */
export function throttled<A extends unknown[]>(ms: number, fn: (...args: A) => void): (...args: A) => void {
  let last = 0;
  let timer: number | null = null;
  let pending: A | null = null;
  return (...args: A) => {
    pending = args;
    const wait = last + ms - Date.now();
    if (wait <= 0) {
      last = Date.now();
      fn(...pending);
    } else if (timer === null) {
      timer = window.setTimeout(() => {
        timer = null;
        last = Date.now();
        fn(...pending!);
      }, wait);
    }
  };
}

/** A panel whose .toggle button hides its .body; remembered per browser. */
export function collapsible(panelId: string): void {
  const panel = $(panelId);
  const btn = panel.querySelector<HTMLButtonElement>(".toggle")!;
  const key = `treemap.${panelId}Collapsed`;
  const set = (c: boolean) => {
    panel.classList.toggle("collapsed", c);
    btn.textContent = c ? "show" : "hide";
    btn.setAttribute("aria-expanded", String(!c));
    try { localStorage.setItem(key, c ? "1" : "0"); } catch { /* storage unavailable */ }
  };
  btn.onclick = () => set(!panel.classList.contains("collapsed"));
  try { set(localStorage.getItem(key) === "1"); } catch { /* storage unavailable */ }
}

/** A readable, YAML-like dump of the config. */
export function yamlish(v: unknown, ind = ""): string {
  if (Array.isArray(v)) {
    if (v.every((x) => x === null || typeof x !== "object")) return `[${v.join(", ")}]`;
    return v.map((x) => `\n${ind}- ` + yamlish(x, ind + "  ").trimStart()).join("");
  }
  if (v && typeof v === "object") {
    return Object.entries(v).map(([k, x]) => `\n${ind}${k}: ${yamlish(x, ind + "  ")}`).join("");
  }
  return v === null ? "null" : String(v);
}

/** Small typed event hub for state changes shared between panels. */
export class Emitter<E extends Record<string, unknown>> {
  private handlers: { [K in keyof E]?: ((v: E[K]) => void)[] } = {};
  on<K extends keyof E>(name: K, fn: (v: E[K]) => void): void {
    (this.handlers[name] ??= []).push(fn);
  }
  emit<K extends keyof E>(name: K, value: E[K]): void {
    for (const fn of this.handlers[name] ?? []) fn(value);
  }
}
