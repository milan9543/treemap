// The virtual WLED's screen: the layout as a phone would film it in a dark room. A tree
// stands on its floor with its branches lit by the LEDs (foliage.ts, as the viewer's
// virtual phone sees it); a flat layout hangs on a dark wall.
import * as THREE from "three";
import { LightGrid, LOOKS, treeGeometry, treeMeshes, useGrid } from "../3d/foliage";
import type { Layout } from "./types";

export const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.domElement.style.display = "block";

export const scene = new THREE.Scene();
scene.background = new THREE.Color(LOOKS.photo.background);
export const camera = new THREE.PerspectiveCamera(55, 1, 0.01, 100);

// An LED: a glow that keeps its colour, nothing when it's off. Size in world metres.
const ledMaterial = new THREE.ShaderMaterial({
  uniforms: { uSize: { value: 0.06 }, uScale: { value: 1.0 } },
  vertexShader: /* glsl */ `
    attribute vec3 ledColor;
    uniform float uSize, uScale;
    varying vec3 vColor;
    void main() {
      vColor = ledColor;
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      gl_Position = projectionMatrix * mv;
      gl_PointSize = max(2.0, uSize * uScale / -mv.z);
    }`,
  fragmentShader: /* glsl */ `
    varying vec3 vColor;
    void main() {
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

const world = new THREE.Group();
scene.add(world);
let colors = new Float32Array(0);
let colorAttr: THREE.BufferAttribute | null = null;
let grid: LightGrid | null = null;
let lastFrame: ArrayBuffer | null = null;

/** Where to look from at the start: in front, the whole layout in view. */
export interface Home { eye: THREE.Vector3; target: THREE.Vector3 }

/** Show a new layout; returns where to stand to see it. */
export function show(layout: Layout): Home {
  world.traverse((o) => (o as THREE.Mesh).geometry?.dispose());
  world.clear();
  grid?.dispose();
  grid = null;
  useGrid(null);

  const pos = Float32Array.from(layout.positions.flat());
  colors = new Float32Array(pos.length);
  colorAttr = new THREE.BufferAttribute(colors, 3).setUsage(THREE.DynamicDrawUsage);
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geom.setAttribute("ledColor", colorAttr);
  const points = new THREE.Points(geom, ledMaterial);
  points.frustumCulled = false;
  world.add(points);

  const half = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  let home: Home;
  if (layout.shape === "tree") {
    world.add(...treeMeshes(treeGeometry(layout), LOOKS.photo));
    grid = new LightGrid(pos, layout.height, layout.radius);
    useGrid(grid);
    const dist = Math.max(layout.radius + 1.6, (layout.height * 0.6) / half);
    home = { eye: new THREE.Vector3(0, 1.5, dist), target: new THREE.Vector3(0, layout.height * 0.5, 0) };
  } else {
    const ys = layout.positions.map((p) => p[1]);
    const y0 = Math.min(...ys), y1 = Math.max(...ys);
    const wall = new THREE.Mesh(
      new THREE.PlaneGeometry(layout.width + 0.6, y1 + 0.5),
      new THREE.MeshBasicMaterial({ color: 0x0d0f12 }));
    wall.position.set(0, (y1 + 0.5) / 2, -0.01);
    world.add(wall);
    const cy = (y0 + y1) / 2;
    const fit = Math.max(((y1 - y0) / 2) * 1.15 / half, ((layout.width / 2) * 1.15) / (half * camera.aspect));
    home = { eye: new THREE.Vector3(0, cy, Math.max(fit, 0.5)), target: new THREE.Vector3(0, cy, 0) };
  }
  if (lastFrame) applyFrame(lastFrame);
  return home;
}

/** A frame of LED colours (led_count × RGB bytes). */
export function applyFrame(buf: ArrayBuffer): void {
  lastFrame = buf;
  const bytes = new Uint8Array(buf);
  const n = Math.min(bytes.length, colors.length);
  for (let i = 0; i < n; i++) colors[i] = bytes[i] / 255;
  colors.fill(0, n);
  if (colorAttr) colorAttr.needsUpdate = true;
  grid?.update(colors);
}

export function resize(w: number, h: number): void {
  camera.aspect = Math.max(w, 1) / Math.max(h, 1);
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  ledMaterial.uniforms.uScale.value =
    renderer.domElement.height / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
}
