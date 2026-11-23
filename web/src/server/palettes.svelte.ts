// The palettes (built-in and the user's own), shared by every control on the page:
// loaded once, and loaded again after a change.
import { api, type Palette, type PaletteFields } from "./api";

export const palettes = $state({ list: [] as Palette[], error: null as string | null });
let loading: Promise<void> | null = null;

export function loadPalettes(force = false): Promise<void> {
  if (!loading || force) {
    loading = api.palettes().then(
      (r) => { palettes.list = r.palettes; palettes.error = null; },
      (e) => { palettes.error = String(e.message ?? e); loading = null; },
    );
  }
  return loading;
}

export const findPalette = (id: string) => palettes.list.find((p) => p.id === id);

export async function savePalette(id: string | null, fields: PaletteFields): Promise<Palette> {
  const saved = id ? await api.putPalette(id, fields) : await api.addPalette(fields);
  await loadPalettes(true);
  return saved;
}

export async function deletePalette(id: string): Promise<void> {
  await api.deletePalette(id);
  await loadPalettes(true);
}

/** A CSS gradient showing a palette's colours as hard-edged stripes. */
export function swatch(colors: string[]): string {
  if (colors.length === 1) return colors[0];
  const w = 100 / colors.length;
  return `linear-gradient(90deg, ${colors.map((c, i) => `${c} ${i * w}% ${(i + 1) * w}%`).join(", ")})`;
}
