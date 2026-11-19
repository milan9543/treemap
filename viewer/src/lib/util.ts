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

export const cm = (m: number) => `${(m * 100).toFixed(1)} cm`;

/** ``[1, 2, 3, 7, 9, 10]`` -> ``1–3, 7, 9–10`` */
export function ranges(indices: number[]): string {
  const parts: string[] = [];
  let start = -1, last = -2;
  for (const i of [...indices, Infinity]) {
    if (i === last + 1) { last = i; continue; }
    if (start >= 0) parts.push(start === last ? String(start) : `${start}–${last}`);
    start = last = i;
  }
  return parts.join(", ");
}
