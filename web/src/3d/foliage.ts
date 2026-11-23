// The simulated tree as you'd see it in a dark room: a trunk, branches covered in
// needles, and a floor, all lit by the LEDs themselves.
//
// 400+ point lights are far too many to shade directly, so LED light is gathered into a
// coarse 3D grid round the tree instead (LightGrid): each LED adds its colour to the
// cells within reach, falling off with distance, and the needles' shader looks the light
// up there with one texture read. Which cells each LED reaches, and how strongly, is
// worked out once per tree; a frame of colours then costs one multiply-add per pair.
import * as THREE from "three";
import type { Branch, Tree } from "../lib/types";

const CELL = 0.038; // m between grid cells
const REACH = 0.28; // m: how far an LED's light carries onto the branches
const SOFT = 0.02; // m: keeps the light finite right next to an LED
const INTENSITY = 0.004; // light at distance d is about INTENSITY / d²

const NEEDLE_W = [0.12, 0.11, 0.05]; // m: width of the needle spray, by branch level
const CARDS = 4; // crossed needle cards round each branch segment
const REPEAT = 0.09; // m of branch per repeat of the needle texture

export class LightGrid {
  readonly texture: THREE.Data3DTexture;
  readonly min: THREE.Vector3;
  readonly dims: THREE.Vector3;
  private readonly start: Int32Array; // LED i's cells are cell[start[i] .. start[i + 1])
  private readonly cell: Int32Array;
  private readonly weight: Float32Array;
  private readonly sum: Float32Array;
  private readonly data: Uint16Array;

  constructor(pos: Float32Array, H: number, R: number) {
    const n = pos.length / 3;
    const reach = n > 1500 ? 0.25 : REACH; // keep the per-frame cost down on huge trees
    const half = R + reach;
    this.min = new THREE.Vector3(-half, 0, -half);
    const nx = Math.ceil((2 * half) / CELL) + 1, ny = Math.ceil((H + reach) / CELL) + 1, nz = nx;
    this.dims = new THREE.Vector3(nx, ny, nz);
    const cells: number[] = [], weights: number[] = [];
    this.start = new Int32Array(n + 1);
    const r = Math.ceil(reach / CELL), reach2 = reach * reach;
    for (let i = 0; i < n; i++) {
      this.start[i] = cells.length;
      const px = pos[i * 3], py = pos[i * 3 + 1], pz = pos[i * 3 + 2];
      if (!Number.isFinite(px + py + pz)) continue;
      const cx = Math.round((px - this.min.x) / CELL), cy = Math.round(py / CELL), cz = Math.round((pz - this.min.z) / CELL);
      for (let z = Math.max(cz - r, 0); z <= Math.min(cz + r, nz - 1); z++)
        for (let y = Math.max(cy - r, 0); y <= Math.min(cy + r, ny - 1); y++)
          for (let x = Math.max(cx - r, 0); x <= Math.min(cx + r, nx - 1); x++) {
            const dx = this.min.x + x * CELL - px, dy = y * CELL - py, dz = this.min.z + z * CELL - pz;
            const d2 = dx * dx + dy * dy + dz * dz;
            if (d2 >= reach2) continue;
            const fade = 1 - d2 / reach2;
            cells.push(((z * ny + y) * nx + x) * 3);
            weights.push((INTENSITY / (d2 + SOFT * SOFT)) * fade * fade);
          }
    }
    this.start[n] = cells.length;
    this.cell = Int32Array.from(cells);
    this.weight = Float32Array.from(weights);
    this.sum = new Float32Array(nx * ny * nz * 3);
    this.data = new Uint16Array(nx * ny * nz * 4);
    this.texture = new THREE.Data3DTexture(this.data, nx, ny, nz);
    this.texture.format = THREE.RGBAFormat;
    this.texture.type = THREE.HalfFloatType;
    this.texture.minFilter = this.texture.magFilter = THREE.LinearFilter;
    this.texture.unpackAlignment = 1;
    this.texture.needsUpdate = true;
  }

  /** Light the grid with a frame of LED colours (0-1 RGB per LED). */
  update(colors: Float32Array): void {
    const { sum, cell, weight, start, data } = this;
    sum.fill(0);
    const n = Math.min(start.length - 1, colors.length / 3);
    for (let i = 0; i < n; i++) {
      const r = colors[i * 3], g = colors[i * 3 + 1], b = colors[i * 3 + 2];
      if (r + g + b === 0) continue;
      for (let k = start[i]; k < start[i + 1]; k++) {
        const c = cell[k], w = weight[k];
        sum[c] += r * w;
        sum[c + 1] += g * w;
        sum[c + 2] += b * w;
      }
    }
    const half = THREE.DataUtils.toHalfFloat;
    for (let j = 0, k = 0; j < sum.length; j += 3, k += 4) {
      data[k] = sum[j] ? half(sum[j]) : 0;
      data[k + 1] = sum[j + 1] ? half(sum[j + 1]) : 0;
      data[k + 2] = sum[j + 2] ? half(sum[j + 2]) : 0;
    }
    this.texture.needsUpdate = true;
  }

  dispose(): void {
    this.texture.dispose();
  }
}

// -- materials ---------------------------------------------------------------------------

const emptyLight = new THREE.Data3DTexture(new Uint16Array(4), 1, 1, 1);
emptyLight.format = THREE.RGBAFormat;
emptyLight.type = THREE.HalfFloatType;
emptyLight.needsUpdate = true;

const litVertex = /* glsl */ `
  attribute float tint;
  varying vec3 vWorld;
  varying vec2 vUv;
  varying float vTint;
  void main() {
    vec4 w = modelMatrix * vec4(position, 1.0);
    vWorld = w.xyz;
    vUv = uv;
    vTint = tint;
    gl_Position = projectionMatrix * viewMatrix * w;
  }`;

const litFragment = /* glsl */ `
  precision highp sampler3D;
  uniform sampler3D uLight;
  uniform vec3 uMin, uDims;
  uniform float uCell;
  uniform sampler2D uMap;
  uniform float uUseMap;
  uniform vec3 uColor, uAmbient;
  uniform float uGain, uSheen, uNeutral;
  uniform vec3 uFadeTo; // the floor fades into the background with distance (vTint)
  uniform float uFade;
  varying vec3 vWorld;
  varying vec2 vUv;
  varying float vTint;
  void main() {
    vec4 tex = uUseMap > 0.5 ? texture2D(uMap, vUv) : vec4(1.0);
    if (tex.a < 0.3) discard;
    float tint = uFade > 0.5 ? 1.0 : vTint;
    vec3 albedo = tex.rgb * uColor * tint;
    vec3 light = texture(uLight, ((vWorld - uMin) / uCell + 0.5) / uDims).rgb * uGain;
    // LED light shows in its own colour: the needles reflect it mostly as a grey of
    // their own brightness would (a red LED makes them red, not just darker green),
    // plus a little gloss.
    vec3 refl = mix(albedo, vec3(max(albedo.r, max(albedo.g, albedo.b))), uNeutral);
    vec3 c = albedo * uAmbient + light * (refl + uSheen * tint);
    c = 1.0 - exp(-c * 1.15); // roll off highlights instead of clipping them to flat colour
    if (uFade > 0.5) c = mix(uFadeTo, c, vTint);
    gl_FragColor = vec4(c, 1.0);
  }`;

type Look = { ambient: number; gain: number; sheen: number; background: number };
const NEUTRAL = 0.75; // 0: LED light tinted by the needles' green; 1: shown in its own colour

/** How the tree looks in the 3D view (a dim room) and to the phone (room lights off,
 *  exposed for the LEDs, so the branches show only where the LEDs light them). */
export const LOOKS = {
  view: { ambient: 0.26, gain: 0.8, sheen: 0.05, background: 0x0b0e13 },
  photo: { ambient: 0.025, gain: 0.6, sheen: 0.04, background: 0x0a0b0d },
} satisfies Record<string, Look>;

const materials: THREE.ShaderMaterial[] = [];

function litMaterial(look: Look, color: number, map: THREE.Texture | null = null, fade = false,
                     glossy = true): THREE.ShaderMaterial {
  const m = new THREE.ShaderMaterial({
    uniforms: {
      uLight: { value: emptyLight },
      uMin: { value: new THREE.Vector3() },
      uDims: { value: new THREE.Vector3(1, 1, 1) },
      uCell: { value: CELL },
      uMap: { value: map },
      uUseMap: { value: map ? 1 : 0 },
      uColor: { value: new THREE.Color(color) },
      uAmbient: { value: new THREE.Color(look.ambient * 0.85, look.ambient * 0.9, look.ambient * 1.1) },
      uGain: { value: look.gain },
      uSheen: { value: glossy ? look.sheen : 0 },
      uNeutral: { value: NEUTRAL },
      // as is: the shader's output isn't colour-converted, like the clear colour's hex
      uFadeTo: { value: new THREE.Color().setHex(look.background, THREE.LinearSRGBColorSpace) },
      uFade: { value: fade ? 1 : 0 },
    },
    vertexShader: litVertex,
    fragmentShader: litFragment,
    side: THREE.DoubleSide,
  });
  materials.push(m);
  return m;
}

/** Point every tree material at a new light grid (null: no LED light). */
export function useGrid(grid: LightGrid | null): void {
  for (const m of materials) {
    m.uniforms.uLight.value = grid ? grid.texture : emptyLight;
    if (grid) {
      m.uniforms.uMin.value.copy(grid.min);
      m.uniforms.uDims.value.copy(grid.dims);
    }
  }
}

// -- geometry ----------------------------------------------------------------------------

// Seeded PRNG (mulberry32), so a tree always looks the same.
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

let needleMap: THREE.CanvasTexture | null = null;

/** A spray of fir needles along a stem: the stem runs up the middle (v), needles angle
 *  out to both sides. Repeats seamlessly along v. */
function needleTexture(): THREE.CanvasTexture {
  if (needleMap) return needleMap;
  const W = 128, Hpx = 256;
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = Hpx;
  const ctx = canvas.getContext("2d")!;
  const rand = rng(1234);
  ctx.lineCap = "round";
  const needle = (x0: number, y0: number, x1: number, y1: number) => {
    for (const dy of [-Hpx, 0, Hpx]) {
      ctx.beginPath();
      ctx.moveTo(x0, y0 + dy);
      ctx.lineTo(x1, y1 + dy);
      ctx.stroke();
    }
  };
  ctx.strokeStyle = "rgb(95, 75, 50)";
  ctx.lineWidth = 4;
  needle(W / 2, 0, W / 2, Hpx);
  for (let y = 0; y < Hpx; y += 1.7) {
    for (const side of [-1, 1]) {
      const ang = THREE.MathUtils.degToRad(48 + 30 * rand());
      const len = W * 0.47 * (0.7 + 0.3 * rand());
      const l = 22 + 22 * rand();
      ctx.strokeStyle = `hsl(${110 + 30 * rand()}, ${45 + 25 * rand()}%, ${l}%)`;
      ctx.lineWidth = 2.8 + 1.4 * rand();
      const x0 = W / 2 + side * 2, y0 = y + rand() * 2;
      needle(x0, y0, x0 + side * len * Math.sin(ang), y0 - len * Math.cos(ang));
    }
    if (rand() < 0.5) { // a needle pointing at you, foreshortened
      ctx.strokeStyle = `hsl(${115 + 25 * rand()}, 55%, ${26 + 18 * rand()}%)`;
      ctx.lineWidth = 2.5;
      const x0 = W / 2 + (rand() - 0.5) * 10;
      needle(x0, y, x0 + (rand() - 0.5) * 30, y - 6 - 10 * rand());
    }
  }
  needleMap = new THREE.CanvasTexture(canvas);
  needleMap.wrapS = THREE.ClampToEdgeWrapping;
  needleMap.wrapT = THREE.RepeatWrapping;
  needleMap.anisotropy = 4;
  return needleMap;
}

const UP = new THREE.Vector3(0, 1, 0);

/** Needle sprays: crossed cards along each branch segment, the widest lying flat like a
 *  fir's. A twig's needles stop short of the LED it holds. */
function needleGeometry(branches: Branch[], H: number, R: number, seed: number): THREE.BufferGeometry {
  const rand = rng(seed * 31 + 7);
  const pos: number[] = [], uv: number[] = [], tint: number[] = [], index: number[] = [];
  const p0 = new THREE.Vector3(), p1 = new THREE.Vector3(), axis = new THREE.Vector3();
  const side0 = new THREE.Vector3(), norm0 = new THREE.Vector3(), side = new THREE.Vector3();
  const corner = new THREE.Vector3();
  for (const b of branches) {
    const pts = b.points;
    const cum = [0];
    for (let k = 1; k < pts.length; k++) cum.push(cum[k - 1] + Math.hypot(
      pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1], pts[k][2] - pts[k - 1][2]));
    const total = cum[cum.length - 1] || 1;
    const vOff = rand() * 10;
    const W = NEEDLE_W[Math.min(b.level, 2)];
    const last = b.level === 2 ? 1 : pts.length - 1; // twigs: needles on the first half
    for (let k = 0; k < last; k++) {
      p0.fromArray(pts[k]);
      p1.fromArray(pts[k + 1]);
      axis.subVectors(p1, p0);
      const len = axis.length();
      if (len < 1e-4) continue;
      axis.divideScalar(len);
      const ext = k === pts.length - 2 && b.level !== 2 ? 0.02 : 0.008; // overlap the joins
      p0.addScaledVector(axis, -0.008);
      p1.addScaledVector(axis, ext);
      side0.crossVectors(axis, UP);
      if (side0.lengthSq() < 1e-6) side0.set(1, 0, 0);
      side0.normalize();
      norm0.crossVectors(side0, axis).normalize();
      const s0 = cum[k] / total, s1 = cum[k + 1] / total;
      const w0 = W * (1 - 0.4 * s0), w1 = W * (1 - 0.4 * s1);
      // darker deep inside the tree, where less room light gets in
      const mid = p0.clone().add(p1).multiplyScalar(0.5);
      const cone = Math.max(R * (1 - mid.y / H), 0.05);
      const depth = Math.min(Math.hypot(mid.x, mid.z) / cone, 1);
      for (let j = 0; j < CARDS; j++) {
        const ang = (j * Math.PI) / CARDS + (rand() - 0.5) * 0.4;
        side.copy(side0).multiplyScalar(Math.cos(ang)).addScaledVector(norm0, Math.sin(ang));
        const f = j === 0 ? 1 : 0.85;
        const base = pos.length / 3;
        const v0 = vOff + (cum[k] - 0.008) / REPEAT, v1 = vOff + (cum[k] + len + ext) / REPEAT;
        for (const [p, w, u, v] of [[p0, -w0, 0, v0], [p0, w0, 1, v0], [p1, w1, 1, v1], [p1, -w1, 0, v1]] as const) {
          corner.copy(p).addScaledVector(side, (w * f) / 2);
          pos.push(corner.x, corner.y, corner.z);
          uv.push(u, v);
        }
        const t = (0.75 + 0.4 * rand()) * (0.55 + 0.45 * depth);
        tint.push(t, t, t, t);
        index.push(base, base + 1, base + 2, base, base + 2, base + 3);
      }
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute("tint", new THREE.Float32BufferAttribute(tint, 1));
  g.setIndex(index);
  return g;
}

/** The wood: a tapered tube along every branch. */
function woodGeometry(branches: Branch[]): THREE.BufferGeometry {
  const pos: number[] = [], index: number[] = [];
  const t = new THREE.Vector3(), n = new THREE.Vector3(), bn = new THREE.Vector3(), p = new THREE.Vector3();
  for (const b of branches) {
    const pts = b.points, sides = b.level === 0 ? 5 : 3;
    const base = pos.length / 3;
    for (let k = 0; k < pts.length; k++) {
      const a = pts[Math.max(k - 1, 0)], c = pts[Math.min(k + 1, pts.length - 1)];
      t.set(c[0] - a[0], c[1] - a[1], c[2] - a[2]).normalize();
      n.crossVectors(t, UP);
      if (n.lengthSq() < 1e-6) n.set(1, 0, 0);
      n.normalize();
      bn.crossVectors(t, n);
      const r = b.radius[0] + (b.radius[1] - b.radius[0]) * (k / (pts.length - 1));
      for (let j = 0; j < sides; j++) {
        const ang = (j / sides) * Math.PI * 2;
        p.fromArray(pts[k]).addScaledVector(n, Math.cos(ang) * r).addScaledVector(bn, Math.sin(ang) * r);
        pos.push(p.x, p.y, p.z);
      }
      if (k > 0) for (let j = 0; j < sides; j++) {
        const a0 = base + (k - 1) * sides + j, a1 = base + (k - 1) * sides + ((j + 1) % sides);
        index.push(a0, a1, a1 + sides, a0, a1 + sides, a0 + sides);
      }
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(index);
  return withTint(g, 1);
}

function withTint(g: THREE.BufferGeometry, value: number | ((x: number, z: number) => number)): THREE.BufferGeometry {
  const p = g.getAttribute("position");
  const tint = new Float32Array(p.count);
  for (let i = 0; i < p.count; i++) tint[i] = typeof value === "number" ? value : value(p.getX(i), p.getZ(i));
  g.setAttribute("tint", new THREE.BufferAttribute(tint, 1));
  if (!g.getAttribute("uv")) g.setAttribute("uv", new THREE.BufferAttribute(new Float32Array(p.count * 2), 2));
  return g;
}

export type TreeGeometry = Record<"needles" | "wood" | "trunk" | "core" | "floor", THREE.BufferGeometry>;

/** Everything drawn for a tree, shared by the 3D view and the phone's scene. */
export function treeGeometry(tree: Tree): TreeGeometry {
  const H = tree.height, R = tree.radius, tr = tree.trunk_radius;
  const branches = tree.branches ?? [];
  const trunk = new THREE.CylinderGeometry(tr * 0.1, tr, H, 14, 1, true);
  trunk.translate(0, H / 2, 0);
  // the dense, dark heart of the tree: you can't see through to the far side
  const core = new THREE.ConeGeometry(R * 0.3, H * 0.86, 24, 1, true);
  core.translate(0, H * 0.47, 0);
  const floorR = Math.max(R * 4, 3.5);
  const floor = new THREE.RingGeometry(0, floorR, 64, 12);
  floor.rotateX(-Math.PI / 2);
  return {
    needles: needleGeometry(branches, H, R, tree.seed),
    wood: woodGeometry(branches),
    trunk: withTint(trunk, 1),
    core: withTint(core, 1),
    floor: withTint(floor, (x, z) => 1 - THREE.MathUtils.smoothstep(Math.hypot(x, z), R * 1.5, floorR)),
  };
}

type Materials = Record<keyof TreeGeometry, THREE.ShaderMaterial>;
const sets = new Map<Look, Materials>();

function materialsFor(look: Look): Materials {
  let m = sets.get(look);
  if (!m) {
    m = {
      needles: litMaterial(look, 0x6f8f76, needleTexture()),
      wood: litMaterial(look, 0x3a2a1d, null, false, false),
      trunk: litMaterial(look, 0x3e2c1f, null, false, false),
      core: litMaterial(look, 0x0a120c, null, false, false),
      floor: litMaterial(look, 0x2b241f, null, true),
    };
    sets.set(look, m);
  }
  return m;
}

/** Meshes for a tree's geometry, lit as ``look``. */
export function treeMeshes(geom: TreeGeometry, look: Look): THREE.Object3D[] {
  const m = materialsFor(look);
  return (Object.keys(geom) as (keyof TreeGeometry)[]).map((k) => {
    const mesh = new THREE.Mesh(geom[k], m[k]);
    mesh.frustumCulled = false;
    if (k === "floor") mesh.position.y = -0.002;
    return mesh;
  });
}
