// The 3D scene: LEDs, cone, trunk, branches and wire path, plus the "photo" scene the
// virtual phone films (always the true LED positions, with branches, no helpers). The
// branches are lit by the LEDs; see foliage.ts.
import * as THREE from "three";
import { app, mapStatus } from "../lib/state.svelte";
import type { Vec3 } from "../lib/types";
import { LightGrid, LOOKS, treeGeometry, treeMeshes, useGrid } from "./foliage";

export const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x0b0e13);
renderer.domElement.style.display = "block"; // the Viewport component places it

export const scene = new THREE.Scene();
export const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);

const ground = new THREE.PolarGridHelper(1.2, 8, 6, 64, 0x1c2430, 0x141a22);
scene.add(ground);
const decor = new THREE.Group(); // cone + trunk
scene.add(decor);
const branches = new THREE.Group();
branches.visible = false;
scene.add(branches);

// LED points: additive glow sprite drawn in a shader so size is in world metres.
const ledVertex = /* glsl */ `
  attribute vec3 ledColor;
  attribute float ledHidden;
  uniform float uSize, uScale;
  varying vec3 vColor;
  varying float vHidden;
  void main() {
    vColor = ledColor;
    vHidden = ledHidden;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = max(2.0, uSize * uScale / -mv.z);
  }`;

export const ledMaterial = new THREE.ShaderMaterial({
  uniforms: {
    uSize: { value: 0.09 }, // halo diameter in metres
    uScale: { value: 1.0 }, // pixels per metre at distance 1, set on resize
    uOffDots: { value: 1.0 },
  },
  vertexShader: ledVertex,
  fragmentShader: /* glsl */ `
    uniform float uOffDots;
    varying vec3 vColor;
    varying float vHidden;
    void main() {
      vec2 p = gl_PointCoord * 2.0 - 1.0;
      float d2 = dot(p, p);
      if (d2 > 1.0) discard;
      float lum = max(vColor.r, max(vColor.g, vColor.b));
      float core = exp(-d2 * 60.0);
      float halo = exp(-d2 * 6.0) * 0.55;
      vec3 c = vColor * (core * 1.4 + halo) + vec3(core * lum * 0.7);
      float dotMask = (1.0 - smoothstep(0.09, 0.16, sqrt(d2))) * uOffDots * (1.0 - min(lum * 4.0, 1.0));
      c += vec3(0.22, 0.25, 0.3) * dotMask;
      gl_FragColor = vec4(c, 1.0);
    }`,
  transparent: true,
  depthWrite: false,
  blending: THREE.AdditiveBlending,
});

// What the phone sees of an LED: a glow that keeps its colour (no white core), nothing
// when it's off, and nothing at all for LEDs listed in sim.hidden_leds.
export const photoLedMaterial = new THREE.ShaderMaterial({
  uniforms: { uSize: { value: 0.06 }, uScale: { value: 1.0 } },
  vertexShader: ledVertex,
  fragmentShader: /* glsl */ `
    varying vec3 vColor;
    varying float vHidden;
    void main() {
      if (vHidden > 0.5) discard;
      vec2 p = gl_PointCoord * 2.0 - 1.0;
      float d2 = dot(p, p);
      if (d2 > 1.0) discard;
      float g = exp(-d2 * 9.0) * 1.6 + exp(-d2 * 3.0) * 0.15;
      gl_FragColor = vec4(vColor * g, 1.0);
    }`,
  transparent: true,
  depthWrite: false,
  blending: THREE.AdditiveBlending,
});

export const photoScene = new THREE.Scene();
photoScene.background = new THREE.Color(0x0a0b0d);
const photoTree = new THREE.Group();
photoScene.add(photoTree);

export const view = {
  truthPos: null as Float32Array | null,
  scanPos: null as Float32Array | null,
  points: null as THREE.Points | null,
  ledCount: 0,
  colors: new Float32Array(0),
  lastFrame: null as ArrayBuffer | null,
};
let colorAttr: THREE.BufferAttribute | null = null;
let hiddenAttr: THREE.BufferAttribute | null = null;
let wire: THREE.Group | null = null;
let grid: LightGrid | null = null; // the LEDs' light on the branches
const compareGroup = new THREE.Group(); // truth -> scanned error lines and markers
scene.add(compareGroup);

/** Error colour: green at 0, yellow at 2.5 cm, red from 5 cm. */
export function errorColor(err_m: number, c = new THREE.Color()): THREE.Color {
  const t = Math.min(err_m / 0.05, 1);
  return c.setHSL((1 - t) * 0.33, 0.85, 0.5);
}

/** Take the tree, map and comparison from the app state; fix the view mode if the one
 *  chosen has nothing to show. */
export function setData(): void {
  const { tree, map } = app;
  view.truthPos = tree ? Float32Array.from(tree.positions.flat()) : null;
  // In the simulator the map is shown aligned onto the truth (as Evaluate does), so the
  // two can be compared; without a truth it's just scaled to a typical tree.
  const cmp = app.compare;
  view.scanPos = cmp ? toArray(cmp.positions) : map && map.positions ? scanToWorld(map.positions) : null;
  if (!modeAvailable(app.viewMode)) app.viewMode = view.truthPos ? "truth" : "scan";
}

export function modeAvailable(m: "truth" | "scan" | "compare"): boolean {
  return m === "truth" ? !!view.truthPos : m === "scan" ? !!view.scanPos : !!(view.truthPos && app.compare);
}

function toArray(pos: (Vec3 | null)[]): Float32Array {
  const out = new Float32Array(pos.length * 3).fill(NaN);
  pos.forEach((p, i) => { if (p) out.set(p, i * 3); });
  return out;
}

// tree_map.json is normalised (y 0..1 over the LEDs, x/z centred on the trunk at the same
// scale). Stretch it onto the ground truth's LED height range so the two overlay.
function scanToWorld(pos: (Vec3 | null)[]): Float32Array {
  let y0 = 0, y1 = 1.8;
  const tree = app.tree;
  if (tree) {
    const ys = tree.positions.map((p) => p[1]);
    y0 = Math.min(...ys);
    y1 = Math.max(...ys);
  }
  const s = y1 - y0;
  const out = new Float32Array(pos.length * 3);
  pos.forEach((p, i) => {
    const ok = !!p && p.every(Number.isFinite);
    out[i * 3] = ok ? p![0] * s : NaN;
    out[i * 3 + 1] = ok ? y0 + p![1] * s : NaN;
    out[i * 3 + 2] = ok ? p![2] * s : NaN;
  });
  return out;
}

function disposeGroup(g: THREE.Object3D): void {
  g.traverse((o) => {
    const m = o as THREE.Mesh;
    if (m.geometry) m.geometry.dispose();
  });
  g.clear();
}

/** Rebuild everything from the current tree, map and mode. */
export function rebuild(): void {
  if (view.points) {
    scene.remove(view.points);
    view.points.geometry.dispose();
    view.points = null;
  }
  grid?.dispose();
  grid = null;
  useGrid(null);
  if (wire) {
    scene.remove(wire);
    disposeGroup(wire);
    wire = null;
  }
  disposeGroup(decor);
  disposeGroup(branches);
  disposeGroup(photoTree);
  disposeGroup(compareGroup);
  const pos = app.viewMode === "scan" ? view.scanPos : view.truthPos;
  if (!pos) return;

  view.ledCount = pos.length / 3;
  view.colors = new Float32Array(view.ledCount * 3);
  colorAttr = new THREE.BufferAttribute(view.colors, 3).setUsage(THREE.DynamicDrawUsage);
  hiddenAttr = new THREE.BufferAttribute(new Float32Array(view.ledCount), 1);
  for (const i of app.config?.hidden_leds ?? []) if (i < view.ledCount) hiddenAttr.setX(i, 1);
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geom.setAttribute("ledColor", colorAttr);
  geom.setAttribute("ledHidden", hiddenAttr);
  // Failed LEDs in a scanned map are NaN; a fixed bound keeps raycasting working.
  geom.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, 1, 0), 10);
  view.points = new THREE.Points(geom, ledMaterial);
  view.points.frustumCulled = false;
  scene.add(view.points);

  // Wire path, one polyline per strip (scanned maps have no strip info: one line).
  wire = new THREE.Group();
  const tree = app.tree;
  const strands = tree ? tree.strands : [{ start: 0, count: view.ledCount }];
  const hues = [0.33, 0.58, 0.08, 0.83, 0.15, 0.5, 0.95, 0.7];
  strands.forEach((s, k) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos.slice(s.start * 3, (s.start + s.count) * 3), 3));
    const m = new THREE.LineBasicMaterial({
      color: new THREE.Color().setHSL(hues[k % hues.length], 0.6, 0.55), transparent: true, opacity: 0.35,
    });
    wire!.add(new THREE.Line(g, m));
  });
  wire.visible = app.layers.wire;
  scene.add(wire);

  const H = tree ? tree.height : 1.8, R = tree ? tree.radius : 0.6;
  const cone = new THREE.Mesh(
    new THREE.ConeGeometry(R, H, 64, 1, true),
    new THREE.MeshBasicMaterial({ color: 0x2f6b46, transparent: true, opacity: 0.07, side: THREE.DoubleSide, depthWrite: false }));
  cone.position.y = H / 2;
  const coneEdges = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.ConeGeometry(R, H, 24, 1, true)),
    new THREE.LineBasicMaterial({ color: 0x2f6b46, transparent: true, opacity: 0.12 }));
  coneEdges.position.y = H / 2;
  const tr = tree ? tree.trunk_radius : 0.04;
  const trunk = new THREE.Mesh(
    new THREE.CylinderGeometry(tr * 0.6, tr, H, 16, 1, true),
    new THREE.MeshBasicMaterial({ color: 0x5a3d26, transparent: true, opacity: 0.18, depthWrite: false }));
  trunk.position.y = H / 2;
  decor.add(cone, coneEdges, trunk);
  decor.visible = app.layers.cone;
  ground.scale.setScalar(Math.max(R * 1.6, 0.6));

  if (tree && view.truthPos) {
    const geom = treeGeometry(tree);
    branches.add(...treeMeshes(geom, LOOKS.view));
    photoTree.add(...treeMeshes(geom, LOOKS.photo));
    grid = new LightGrid(view.truthPos, H, R);
    useGrid(grid);
    const pg = new THREE.BufferGeometry();
    pg.setAttribute("position", new THREE.BufferAttribute(view.truthPos, 3));
    pg.setAttribute("ledColor", colorAttr);
    pg.setAttribute("ledHidden", hiddenAttr);
    const photoPoints = new THREE.Points(pg, photoLedMaterial);
    photoPoints.frustumCulled = false;
    photoTree.add(photoPoints);
  }
  if (app.viewMode === "compare") buildCompare();
  if (view.lastFrame) applyFrame(view.lastFrame);
}

function buildCompare(): void {
  const cmp = app.compare, truth = view.truthPos;
  if (!cmp || !truth) return;
  const line: number[] = [], lineCol: number[] = [], mark: number[] = [], markCol: number[] = [];
  const c = new THREE.Color();
  cmp.positions.forEach((p, i) => {
    const err = cmp.errors_m[i];
    if (!p || err === null) return;
    errorColor(err, c);
    line.push(truth[i * 3], truth[i * 3 + 1], truth[i * 3 + 2], ...p);
    lineCol.push(c.r, c.g, c.b, c.r, c.g, c.b);
    mark.push(...p);
    markCol.push(c.r, c.g, c.b);
  });
  const lg = new THREE.BufferGeometry();
  lg.setAttribute("position", new THREE.Float32BufferAttribute(line, 3));
  lg.setAttribute("color", new THREE.Float32BufferAttribute(lineCol, 3));
  compareGroup.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9 })));
  const mg = new THREE.BufferGeometry();
  mg.setAttribute("position", new THREE.Float32BufferAttribute(mark, 3));
  mg.setAttribute("color", new THREE.Float32BufferAttribute(markCol, 3));
  compareGroup.add(new THREE.Points(mg, new THREE.PointsMaterial({ vertexColors: true, size: 0.014, sizeAttenuation: true })));
}

/** A frame of LED colours (led_count × RGB bytes) from the server. */
export function applyFrame(buf: ArrayBuffer): void {
  view.lastFrame = buf;
  const bytes = new Uint8Array(buf);
  const colors = view.colors;
  const n = Math.min(bytes.length, colors.length);
  for (let i = 0; i < n; i++) colors[i] = bytes[i] / 255;
  for (let i = n; i < colors.length; i++) colors[i] = 0;
  if (colorAttr) colorAttr.needsUpdate = true;
  grid?.update(colors);
  const leds = bytes.length / 3;
  if (app.frameLeds !== leds) app.frameLeds = leds;
}

export function setToggle(name: "off" | "cone" | "wire" | "branch", on: boolean): void {
  if (name === "off") ledMaterial.uniforms.uOffDots.value = on ? 1 : 0;
  else if (name === "cone") decor.visible = on;
  else if (name === "wire" && wire) wire.visible = on;
  else if (name === "branch") {
    branches.visible = on;
    ground.visible = !on; // the tree stands on its own floor
  }
}

const raycaster = new THREE.Raycaster();
raycaster.params.Points.threshold = 0.025;

/** The LED under the pointer, if any. */
export function pickLed(clientX: number, clientY: number): number | null {
  if (!view.points) return null;
  const r = renderer.domElement.getBoundingClientRect();
  const mouse = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(mouse, camera);
  const hit = raycaster.intersectObject(view.points)[0];
  return hit && hit.index !== undefined ? hit.index : null;
}

export function describeLed(i: number): string {
  const tree = app.tree;
  const strip = tree ? tree.strands.findIndex((s) => i >= s.start && i < s.start + s.count) : -1;
  const rgb = [0, 1, 2].map((k) => Math.round(view.colors[i * 3 + k] * 255)).join(", ");
  const st = mapStatus(i);
  const err = app.compare?.errors_m[i];
  const off = err === undefined ? "" : err === null ? " · not placed" : ` · off by ${(err * 100).toFixed(1)} cm`;
  return `#${i}${strip >= 0 ? ` · strip ${strip + 1}` : ""}${st ? ` · ${st}` : ""}${off} · rgb(${rgb})`;
}

let size = { w: 1, h: 1 };

/** Fit the view to ``w`` × ``h`` CSS pixels (or the last size, after a FOV change). */
export function resize(w = size.w, h = size.h): void {
  size = { w: Math.max(w, 1), h: Math.max(h, 1) };
  camera.aspect = size.w / size.h;
  camera.updateProjectionMatrix();
  renderer.setSize(size.w, size.h);
  ledMaterial.uniforms.uScale.value =
    renderer.domElement.height / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
}
