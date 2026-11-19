// The virtual phone: films the photo scene from wherever the view camera is, shows it in
// the inset, and while a scan is listening streams the photos to /ws/camera as JPEGs
// (see treemap/cameras/browser.py for the wire format). The scan's detections come back
// as "scan.detections" messages and are drawn over the inset.
import * as THREE from "three";
import { WALK_FOV, walking } from "./controls";
import { camera, photoLedMaterial, photoScene } from "./scene";
import { state } from "./state";
import type { Detections, JobState } from "./types";
import { $ } from "./util";

const W = 640, H = 480;

const phoneRenderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true });
phoneRenderer.setPixelRatio(1);
phoneRenderer.setSize(W, H, false);
phoneRenderer.autoClear = false;
const screen = $("phone").querySelector(".screen")!;
screen.prepend(phoneRenderer.domElement);
const overlay = $<HTMLCanvasElement>("phone-overlay");
const octx = overlay.getContext("2d")!;

const phoneCam = new THREE.PerspectiveCamera(WALK_FOV, W / H, 0.05, 50);
photoLedMaterial.uniforms.uScale.value = H / (2 * Math.tan(THREE.MathUtils.degToRad(WALK_FOV / 2)));

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

let lastShot = 0, encoding = false, sent = 0, sentAt = performance.now(), sendFps = 0;
let detections: Detections | null = null, detectionsAt = 0;

const streaming = () => state.scanners > 0;

/** Call once per animation frame. */
export function tick(now: number): void {
  const visible = walking || streaming();
  $("phone").classList.toggle("on", visible);
  if (!visible) return;
  const fps = state.serverConfig?.config?.scan.camera_fps ?? 24;
  if (now - lastShot < 1000 / fps - 2) return;
  lastShot = now;

  phoneCam.position.copy(camera.position);
  phoneCam.quaternion.copy(camera.quaternion);
  phoneCam.updateMatrixWorld();
  noiseMat.uniforms.uSeed.value = (now % 1000) / 7.0;
  phoneRenderer.clear();
  phoneRenderer.render(photoScene, phoneCam);
  phoneRenderer.render(noiseScene, noiseCam);
  const t = now / 1000;

  if (streaming() && socket?.readyState === WebSocket.OPEN && !encoding && socket.bufferedAmount < 2e6) {
    encoding = true;
    const header = {
      t, fov_v: WALK_FOV,
      eye: phoneCam.position.toArray(),
      quat: phoneCam.quaternion.toArray(),
    };
    phoneRenderer.domElement.toBlob(async (blob) => {
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
  if (now - sentAt > 1000) {
    sendFps = sent;
    sent = 0;
    sentAt = now;
  }
  drawOverlay(now);
  hud();
}

export function onDetections(d: Detections): void {
  detections = d;
  detectionsAt = performance.now();
}

function drawOverlay(now: number): void {
  octx.clearRect(0, 0, W, H);
  if (!detections || now - detectionsAt > 1500 || !detections.size[0]) return;
  const sx = W / detections.size[0], sy = H / detections.size[1];
  octx.lineWidth = 1.5;
  octx.font = "11px ui-monospace, Menlo, monospace";
  for (const [u, v, led] of detections.blobs) {
    const x = u * sx, y = v * sy;
    octx.strokeStyle = led >= 0 ? "rgba(127, 209, 168, 0.9)" : "rgba(160, 170, 185, 0.55)";
    octx.beginPath();
    octx.arc(x, y, led >= 0 ? 6 : 4, 0, Math.PI * 2);
    octx.stroke();
    if (led >= 0 && led % 5 === 0) {
      octx.fillStyle = "rgba(220, 240, 230, 0.9)";
      octx.fillText(String(led), x + 7, y - 5);
    }
  }
}

function hud(): void {
  const job: JobState = state.job;
  const p = job.kind === "scan" && job.status === "running" ? job.progress : null;
  let left = streaming() ? `<span class="rec">●</span> sending ${sendFps} fps` : "phone preview";
  let right = "";
  if (p) {
    const phase = p.phase === "flashing" ? `flashing ${p.remaining?.toFixed(0) ?? ""} s`
      : p.phase === "solving" ? "solving…" : "status colours";
    left += ` · round <b>${p.round}</b> · ${phase}`;
    right = p.counts && p.phase === "status"
      ? `<b>${p.counts.ok}</b> ok · ${p.counts.interpolated} interp · ${p.counts.failed} unknown`
      : `<b>${p.identified ?? 0}</b> LEDs identified`;
  }
  $("phone-left").innerHTML = left;
  $("phone-right").innerHTML = right;
}
