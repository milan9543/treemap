// The virtual phone: films the photo scene from wherever the view camera is and, while a
// scan is listening, streams the photos to /ws/camera as JPEGs (see
// treemap/cameras/browser.py for the wire format). PhoneInset.svelte shows its canvas.
import * as THREE from "three";
import { app } from "../lib/state.svelte";
import { WALK_FOV } from "./controls";
import { camera, photoLedMaterial, photoScene } from "./scene";

export const PHONE_W = 640, PHONE_H = 480;

const phoneRenderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true });
phoneRenderer.setPixelRatio(1);
phoneRenderer.setSize(PHONE_W, PHONE_H, false);
phoneRenderer.autoClear = false;
export const phoneCanvas = phoneRenderer.domElement;

const phoneCam = new THREE.PerspectiveCamera(WALK_FOV, PHONE_W / PHONE_H, 0.05, 50);
photoLedMaterial.uniforms.uScale.value = PHONE_H / (2 * Math.tan(THREE.MathUtils.degToRad(WALK_FOV / 2)));

// A little sensor noise on top of each photo.
const noiseScene = new THREE.Scene();
const noiseCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
const noiseMat = new THREE.ShaderMaterial({
  uniforms: { uSeed: { value: 0 } },
  vertexShader: "void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }",
  fragmentShader: /* glsl */ `
    uniform float uSeed;
    float hash(vec2 p) { return fract(sin(dot(p + uSeed, vec2(12.9898, 78.233))) * 43758.5453); }
    void main() { gl_FragColor = vec4(vec3(hash(gl_FragCoord.xy)) * 0.025, 1.0); }`,
  blending: THREE.AdditiveBlending,
  depthTest: false,
  transparent: true,
});
noiseScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), noiseMat));

let socket: WebSocket | null = null;
function connect(): void {
  socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/camera?role=phone`);
  socket.binaryType = "arraybuffer";
  socket.onclose = () => { socket = null; setTimeout(connect, 1000); };
}
connect();

let lastShot = 0, encoding = false, sent = 0, sentAt = 0;

/** Whether the phone films at all: while walking, or while a scan listens. */
export const phoneActive = () => app.walking || app.scanners > 0;

/** Call once per animation frame. */
export function tick(now: number): void {
  if (now - sentAt > 1000) {
    if (app.phoneFps !== sent) app.phoneFps = sent;
    sent = 0;
    sentAt = now;
  }
  if (!phoneActive()) return;
  const fps = app.config?.config?.scan.camera_fps ?? 24;
  if (now - lastShot < 1000 / fps - 2) return;
  lastShot = now;

  phoneCam.position.copy(camera.position);
  phoneCam.quaternion.copy(camera.quaternion);
  phoneCam.updateMatrixWorld();
  noiseMat.uniforms.uSeed.value = (now % 1000) / 7.0;
  phoneRenderer.clear();
  phoneRenderer.render(photoScene, phoneCam);
  phoneRenderer.render(noiseScene, noiseCam);

  const streaming = app.scanners > 0;
  if (!streaming || socket?.readyState !== WebSocket.OPEN || encoding || socket.bufferedAmount > 2e6) return;
  encoding = true;
  const header = {
    t: now / 1000, fov_v: WALK_FOV,
    eye: phoneCam.position.toArray(),
    quat: phoneCam.quaternion.toArray(),
  };
  phoneCanvas.toBlob(async (blob) => {
    encoding = false;
    if (!blob || socket?.readyState !== WebSocket.OPEN) return;
    const head = new TextEncoder().encode(JSON.stringify(header));
    const out = new Uint8Array(4 + head.length + blob.size);
    new DataView(out.buffer).setUint32(0, head.length, true);
    out.set(head, 4);
    out.set(new Uint8Array(await blob.arrayBuffer()), 4 + head.length);
    socket.send(out);
    sent++;
  }, "image/jpeg", 0.85);
}
