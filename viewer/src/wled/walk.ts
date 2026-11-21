// Walking round the layout, as in the viewer's walk mode: WASD or the arrows to move,
// Space up, Shift down, and the mouse to look once the view has captured it (click).
import * as THREE from "three";
import { PointerLockControls } from "three/addons/controls/PointerLockControls.js";
import { camera, renderer } from "./scene";
import type { Home } from "./scene";

const SPEED = 1.4; // m/s
const MOVE_KEYS = new Set(["KeyW", "KeyA", "KeyS", "KeyD", "Space", "ShiftLeft", "ShiftRight",
  "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);

export const look = new PointerLockControls(camera, renderer.domElement);
const keys = new Set<string>();

export function goHome(home: Home): void {
  camera.position.copy(home.eye);
  camera.up.set(0, 1, 0);
  camera.lookAt(home.target);
}

/** Track a movement key; false if the key isn't one (or a form field has the focus). */
export function walkKey(e: KeyboardEvent, down: boolean): boolean {
  if (!MOVE_KEYS.has(e.code)) return false;
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
  const fwd = (keys.has("KeyW") || keys.has("ArrowUp") ? 1 : 0) - (keys.has("KeyS") || keys.has("ArrowDown") ? 1 : 0);
  const side = (keys.has("KeyD") || keys.has("ArrowRight") ? 1 : 0) - (keys.has("KeyA") || keys.has("ArrowLeft") ? 1 : 0);
  const up = (keys.has("Space") ? 1 : 0) - (keys.has("ShiftLeft") || keys.has("ShiftRight") ? 1 : 0);
  if (fwd) look.moveForward(fwd * SPEED * dt);
  if (side) look.moveRight(side * SPEED * dt);
  if (up) camera.position.y = THREE.MathUtils.clamp(camera.position.y + up * SPEED * 0.7 * dt, 0.15, 4);
}
