// The simulated tree, as the virtual WLED serves it (treemap/sim/tree.py).

export type Vec3 = [number, number, number];

export interface StripSpec { leds: number; length: number | null; start: string }
export interface TreeSpec {
  strips: StripSpec[];
  height: number | null;
  radius: number | null;
  layout: string;
  quirks: boolean;
  seed: number | null;
}

export interface Strand {
  start: number;
  count: number;
  spacing: number;
  turns: number;
  index_from_top: boolean;
}

export interface Tree {
  version: number;
  seed: number;
  led_count: number;
  height: number;
  radius: number;
  trunk_radius: number;
  layout: string;
  strands: Strand[];
  positions: Vec3[];
  spec?: TreeSpec;
  warnings?: string[];
  branches?: Branch[];
}

/** A branch of the simulated tree: level 0 main branch (or leader), 1 side branchlet,
 *  2 twig holding an LED. Points run from its base out to its tip. */
export interface Branch {
  level: number;
  radius: [number, number];
  points: Vec3[];
}
