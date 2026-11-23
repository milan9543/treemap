// How you look at the layout. Two modes:
//
// - rotate (the default): drag to turn round the layout, scroll to zoom, right-drag to
//   pan. It can also turn by itself, slowly, so a phone held still in front of the
//   screen films the tree as if walking round it.
// - walk: first person: WASD or the arrows to move, Space
//   up, Shift down, and the mouse to look once the view has captured it (click).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { PointerLockControls } from "three/addons/controls/PointerLockControls.js";
import { camera, renderer } from "./scene";
import type { Home } from "./scene";

export type Mode = "rotate" | "walk";

const SPEED = 1.4; // m/s
const MOVE_KEYS = new Set(["KeyW", "KeyA", "KeyS", "KeyD", "Space", "ShiftLeft", "ShiftRight",
  "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);

export const orbit = new OrbitControls(camera, renderer.domElement);
orbit.enableDamping = true;
orbit.dampingFactor = 0.08;
export const look = new PointerLockControls(camera, renderer.domElement);
const keys = new Set<string>();
let mode: Mode = "rotate";

/** Turn by itself, once round in `seconds` (0: don't). */
export function autoRotate(seconds: number): void {
  orbit.autoRotate = seconds > 0;
  orbit.autoRotateSpeed = seconds > 0 ? 60 / seconds : 0; // three: once round in 60/speed s
}

export function setMode(m: Mode, home: Home | null): void {
  mode = m;
  orbit.enabled = m === "rotate";
  keys.clear();
  if (m === "rotate") look.unlock();
  if (home) goHome(home);
}

export function goHome(home: Home): void {
  camera.position.copy(home.eye);
  camera.up.set(0, 1, 0);
  orbit.target.copy(home.target);
  camera.lookAt(home.target);
  if (mode === "rotate") orbit.update();
}

/** Track a walking key; false if it isn't one, or not walking (or a form field has the focus). */
export function walkKey(e: KeyboardEvent, down: boolean): boolean {
  if (mode !== "walk" || !MOVE_KEYS.has(e.code)) return false;
  const t = e.target as HTMLElement | null;
  if (down && t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return false;
  if (down) keys.add(e.code);
  else keys.delete(e.code);
  e.preventDefault();
  return true;
}
window.addEventListener("blur", () => keys.clear());

let last = performance.now();

/** Call once per animation frame. */
export function update(): void {
  const now = performance.now();
  const dt = Math.min((now - last) / 1000, 0.1);
  last = now;
  if (mode === "rotate") {
    orbit.update(dt);
    return;
  }
  const fwd = (keys.has("KeyW") || keys.has("ArrowUp") ? 1 : 0) - (keys.has("KeyS") || keys.has("ArrowDown") ? 1 : 0);
  const side = (keys.has("KeyD") || keys.has("ArrowRight") ? 1 : 0) - (keys.has("KeyA") || keys.has("ArrowLeft") ? 1 : 0);
  const up = (keys.has("Space") ? 1 : 0) - (keys.has("ShiftLeft") || keys.has("ShiftRight") ? 1 : 0);
  if (fwd) look.moveForward(fwd * SPEED * dt);
  if (side) look.moveRight(side * SPEED * dt);
  if (up) camera.position.y = THREE.MathUtils.clamp(camera.position.y + up * SPEED * 0.7 * dt, 0.15, 4);
}
