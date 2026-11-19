// The 3D scene: LEDs, cone, trunk, branches and wire path, plus the "photo" scene the
// virtual phone films (always the true LED positions, with branches, no helpers).
import * as THREE from "three";
import { mapStatus, state } from "./state";
import type { Vec3 } from "./types";
import { $ } from "./util";

export const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setClearColor(0x07090d);
document.body.prepend(renderer.domElement);

export const scene = new THREE.Scene();
export const camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 0.01, 100);

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

export type Mode = "truth" | "scan" | "compare";

export const view = {
  mode: "truth" as Mode,
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
const compareGroup = new THREE.Group(); // truth -> scanned error lines and markers
scene.add(compareGroup);

/** Error colour: green at 0, yellow at 2.5 cm, red from 5 cm. */
export function errorColor(err_m: number, c = new THREE.Color()): THREE.Color {
  const t = Math.min(err_m / 0.05, 1);
  return c.setHSL((1 - t) * 0.33, 0.85, 0.5);
}

export function setData(): void {
  const { tree, map } = state;
  view.truthPos = tree ? Float32Array.from(tree.positions.flat()) : null;
  // In the simulator the map is shown aligned onto the truth (as Evaluate does), so the
  // two can be compared; without a truth it's just scaled to a typical tree.
  const cmp = state.compare;
  view.scanPos = cmp ? toArray(cmp.positions) : map && map.positions ? scanToWorld(map.positions) : null;
  if (!view.truthPos && view.scanPos) view.mode = "scan";
  if (!view.scanPos) view.mode = "truth";
  if (view.mode === "compare" && !(cmp && view.truthPos)) view.mode = view.truthPos ? "truth" : "scan";
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
  const tree = state.tree;
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
  if (wire) {
    scene.remove(wire);
    disposeGroup(wire);
    wire = null;
  }
  disposeGroup(decor);
  disposeGroup(branches);
  disposeGroup(photoTree);
  disposeGroup(compareGroup);
  const pos = view.mode === "scan" ? view.scanPos : view.truthPos;
  if (!pos) return;

  view.ledCount = pos.length / 3;
  view.colors = new Float32Array(view.ledCount * 3);
  colorAttr = new THREE.BufferAttribute(view.colors, 3).setUsage(THREE.DynamicDrawUsage);
  hiddenAttr = new THREE.BufferAttribute(new Float32Array(view.ledCount), 1);
  for (const i of state.serverConfig?.hidden_leds ?? []) if (i < view.ledCount) hiddenAttr.setX(i, 1);
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
  const tree = state.tree;
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
  wire.visible = $("t-wire").classList.contains("active");
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
  decor.visible = $("t-cone").classList.contains("active");
  ground.scale.setScalar(Math.max(R * 1.6, 0.6));

  if (tree && view.truthPos) {
    buildBranches(branches, tree.seed, H, R, tr, 0x0d2216, 0x08150e);
    buildBranches(photoTree, tree.seed, H, R, tr, 0x07100b, 0x040806);
    const pg = new THREE.BufferGeometry();
    pg.setAttribute("position", new THREE.BufferAttribute(view.truthPos, 3));
    pg.setAttribute("ledColor", colorAttr);
    pg.setAttribute("ledHidden", hiddenAttr);
    const photoPoints = new THREE.Points(pg, photoLedMaterial);
    photoPoints.frustumCulled = false;
    photoTree.add(photoPoints);
  }
  if (view.mode === "compare") buildCompare();
  if (view.lastFrame) applyFrame(view.lastFrame);
}

function buildCompare(): void {
  const cmp = state.compare, truth = view.truthPos;
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

// Seeded PRNG (mulberry32), so a tree always gets the same branches.
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

/** Branches that hide LEDs: an opaque core round the trunk (the back of the tree is
 *  hidden from the front) and clumps of needles between the LEDs nearer the surface. */
function buildBranches(group: THREE.Group, seed: number, H: number, R: number, trunkR: number,
                       clump: number, core: number): void {
  const rand = rng(seed * 7919 + 17);
  const coreMesh = new THREE.Mesh(
    new THREE.ConeGeometry(R * 0.3, H * 0.96, 32, 1),
    new THREE.MeshBasicMaterial({ color: core }));
  coreMesh.position.y = H * 0.48;
  const trunk = new THREE.Mesh(
    new THREE.CylinderGeometry(trunkR, trunkR * 1.2, H * 0.15, 12),
    new THREE.MeshBasicMaterial({ color: 0x1a120c }));
  trunk.position.y = H * 0.075;
  group.add(coreMesh, trunk);

  const count = Math.round(120 * (R / 0.65) * (H / 1.85));
  const geom = new THREE.IcosahedronGeometry(1, 1);
  const mesh = new THREE.InstancedMesh(geom, new THREE.MeshBasicMaterial({ color: 0xffffff }), count);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler();
  const c = new THREE.Color();
  for (let k = 0; k < count; k++) {
    // more clumps low down, where the tree is wider
    const y = H * (1 - Math.sqrt(rand())) * 0.95;
    const rAt = R * (1 - y / H);
    const a = rand() * Math.PI * 2;
    const d = rAt * (0.45 + 0.5 * rand());
    const size = (0.03 + 0.045 * rand()) * Math.max(rAt / R, 0.35) + 0.015;
    e.set(rand() * Math.PI, rand() * Math.PI, rand() * Math.PI);
    q.setFromEuler(e);
    m.compose(new THREE.Vector3(d * Math.cos(a), y, d * Math.sin(a)), q,
      new THREE.Vector3(size * 1.5, size * 0.55, size));
    mesh.setMatrixAt(k, m);
    c.setHex(clump).multiplyScalar(0.7 + 0.6 * rand());
    mesh.setColorAt(k, c);
  }
  group.add(mesh);
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
  const w = $("warn");
  if (view.ledCount && bytes.length !== view.ledCount * 3) {
    w.textContent = `Frames have ${bytes.length / 3} LEDs but the tree has ${view.ledCount}. ` +
      "Match led_count in config.yaml to the strips.";
    w.style.display = "block";
  } else {
    w.style.display = "none";
  }
}

export function setToggle(name: "off" | "cone" | "wire" | "branch", on: boolean): void {
  if (name === "off") ledMaterial.uniforms.uOffDots.value = on ? 1 : 0;
  else if (name === "cone") decor.visible = on;
  else if (name === "wire" && wire) wire.visible = on;
  else if (name === "branch") branches.visible = on;
}

const raycaster = new THREE.Raycaster();
raycaster.params.Points.threshold = 0.025;

/** The LED under the pointer, if any. */
export function pickLed(clientX: number, clientY: number): number | null {
  if (!view.points) return null;
  const mouse = new THREE.Vector2((clientX / window.innerWidth) * 2 - 1, -(clientY / window.innerHeight) * 2 + 1);
  raycaster.setFromCamera(mouse, camera);
  const hit = raycaster.intersectObject(view.points)[0];
  return hit && hit.index !== undefined ? hit.index : null;
}

export function describeLed(i: number): string {
  const tree = state.tree;
  const strip = tree ? tree.strands.findIndex((s) => i >= s.start && i < s.start + s.count) : -1;
  const rgb = [0, 1, 2].map((k) => Math.round(view.colors[i * 3 + k] * 255)).join(", ");
  const st = mapStatus(i);
  const err = state.compare?.errors_m[i];
  const off = err === undefined ? "" : err === null ? " · not placed" : ` · off by ${(err * 100).toFixed(1)} cm`;
  return `#${i}${strip >= 0 ? ` · strip ${strip + 1}` : ""}${st ? ` · ${st}` : ""}${off} · rgb(${rgb})`;
}

export function resize(): void {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  ledMaterial.uniforms.uScale.value =
    renderer.domElement.height / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
}
