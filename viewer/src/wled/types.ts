// What the virtual WLED serves (treemap/sim/virtual_wled.py).
import type { Tree, Vec3 } from "../lib/types";

export interface FlatLayout {
  shape: "flat";
  seed: number;
  pattern: "rows" | "spiral";
  width: number;
  height: number;
  gap: number;
  led_count: number;
  strands: { start: number; count: number; spacing: number; reversed: boolean }[];
  positions: Vec3[];
}

export type Layout = (Tree & { shape: "tree" }) | FlatLayout;

export interface Status {
  type: "status";
  led_count: number;
  live: boolean;
  fps: number;
  source: string | null;
  controller: string;
  shape: "tree" | "flat";
}
