// Orbit (drag round the tree) and walk (first person: WASD, mouse look) camera modes.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { PointerLockControls } from "three/addons/controls/PointerLockControls.js";
import { app, type Layer } from "../lib/state.svelte";
import { camera, renderer, resize } from "./scene";

export const WALK_FOV = 55; // degrees, vertical: the same as the phone's, so you see what it sees
const ORBIT_FOV = 40;
const SPEED = 1.4; // m/s
const EYE = 1.5; // m

const orbit = new OrbitControls(camera, renderer.domElement);
orbit.enableDamping = true;
orbit.dampingFactor = 0.08;
let userMoved = false;
let lastHeight = -1;
orbit.addEventListener("start", () => { userMoved = true; });

const look = new PointerLockControls(camera, renderer.domElement);
const keys = new Set<string>();
// Walking shows the tree as it is: branches only, no unlit-LED dots, cone or wire.
// Leaving walk mode restores the layers from before.
const WALK_LAYERS: Record<Layer, boolean> = { off: false, cone: false, branch: true, wire: false };
let layersBefore: Record<Layer, boolean> | null = null;

const treeSize = () => ({ H: app.tree?.height ?? 1.8, R: app.tree?.radius ?? 0.6 });

export function resetView(): void {
  const { H, R } = treeSize();
  if (app.walking) {
    camera.position.set(0, EYE, R + 1.6);
    camera.lookAt(0, H * 0.5, 0);
    return;
  }
  const half = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  if (!app.tree && app.map?.shape === "flat") {
    // a 2D map stands upright like the photo it came from: look at it square-on, fitting
    // its width too (the map's x is in the same units as its 0-1 height, shown H tall)
    const xs = app.map.positions.flatMap((p) => (p && Number.isFinite(p[0]) ? [Math.abs(p[0]) * H] : []));
    const halfW = Math.max(0.1, ...xs) * 1.1;
    const dist = Math.max((H * 0.58) / half, halfW / (half * camera.aspect));
    orbit.target.set(0, H * 0.5, 0);
    camera.position.set(0, H * 0.5, dist);
  } else {
    const dist = (H * 0.72) / half;
    orbit.target.set(0, H * 0.45, 0);
    camera.position.set(0, H * 0.7, dist);
  }
  orbit.update();
  userMoved = false;
  lastHeight = H;
}

/** After the tree changes: reset the view unless the user has moved it (same tree size). */
export function treeChanged(): void {
  const { H } = treeSize();
  if (!app.walking && (!userMoved || lastHeight !== H)) resetView();
}

export function setWalking(on: boolean): void {
  if (on === app.walking) return;
  app.walking = on;
  const { H, R } = treeSize();
  if (on) {
    layersBefore = { ...app.layers };
    Object.assign(app.layers, WALK_LAYERS);
    orbit.enabled = false;
    camera.fov = WALK_FOV;
    // start at eye height a couple of metres out, on the side the orbit view was on
    const dir = new THREE.Vector3(camera.position.x, 0, camera.position.z);
    if (dir.lengthSq() < 1e-6) dir.set(0, 0, 1);
    dir.normalize().multiplyScalar(R + 1.6);
    camera.position.set(dir.x, EYE, dir.z);
    camera.up.set(0, 1, 0);
    camera.lookAt(0, H * 0.5, 0);
    look.lock();
  } else {
    if (layersBefore) Object.assign(app.layers, layersBefore);
    layersBefore = null;
    look.unlock();
    keys.clear();
    camera.fov = ORBIT_FOV;
    // orbit round the point in front of the camera, at the trunk's distance
    const fwd = camera.getWorldDirection(new THREE.Vector3());
    const dist = Math.max(Math.hypot(camera.position.x, camera.position.z), 1);
    orbit.target.copy(camera.position).addScaledVector(fwd, dist);
    orbit.target.y = THREE.MathUtils.clamp(orbit.target.y, 0, H);
    orbit.enabled = true;
    userMoved = true;
  }
  resize();
}

/** Capture the mouse for looking round (needs a click or key press to be allowed). */
export function lock(): void {
  if (app.walking) look.lock();
}

look.addEventListener("lock", () => { app.locked = true; });
look.addEventListener("unlock", () => { app.locked = false; keys.clear(); });

const MOVE_KEYS = new Set(["KeyW", "KeyA", "KeyS", "KeyD", "Space", "ShiftLeft", "ShiftRight",
  "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);

export function walkKey(e: KeyboardEvent, down: boolean): boolean {
  if (!app.walking || !app.locked || !MOVE_KEYS.has(e.code)) return false;
  if (down) keys.add(e.code);
  else keys.delete(e.code);
  e.preventDefault();
  return true;
}
window.addEventListener("keyup", (e) => { keys.delete(e.code); });
window.addEventListener("blur", () => keys.clear());

let last = performance.now();

/** Call once per animation frame. */
export function update(): void {
  const now = performance.now();
  const dt = Math.min((now - last) / 1000, 0.1);
  last = now;
  if (!app.walking) {
    orbit.update();
    return;
  }
  const fwd = (keys.has("KeyW") || keys.has("ArrowUp") ? 1 : 0) - (keys.has("KeyS") || keys.has("ArrowDown") ? 1 : 0);
  const side = (keys.has("KeyD") || keys.has("ArrowRight") ? 1 : 0) - (keys.has("KeyA") || keys.has("ArrowLeft") ? 1 : 0);
  const up = (keys.has("Space") ? 1 : 0) - (keys.has("ShiftLeft") || keys.has("ShiftRight") ? 1 : 0);
  if (fwd) look.moveForward(fwd * SPEED * dt);
  if (side) look.moveRight(side * SPEED * dt);
  if (up) camera.position.y = THREE.MathUtils.clamp(camera.position.y + up * SPEED * 0.7 * dt, 0.15, 4);
}
