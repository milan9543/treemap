<script lang="ts">
  // A device's LEDs where the scan placed them, lit as they are now: the frames the
  // server sends the device (or only keeps, in preview), fetched a few times a second.
  // Unlit LEDs show as faint dots so the shape stays visible. Drag to turn, scroll to
  // zoom.
  import * as THREE from "three";
  import { OrbitControls } from "three/addons/controls/OrbitControls.js";
  import { onDestroy, onMount } from "svelte";
  import type { DeviceApi, MapInfo } from "./api";

  let { dev, map, gamma = 1 }: { dev: DeviceApi; map: MapInfo; gamma?: number } = $props();

  const FRAME_MS = 50; // ~20 fps
  const UNLIT = 0.09; // how bright an unlit LED is drawn

  let host: HTMLDivElement;
  let renderer: THREE.WebGLRenderer;
  let camera: THREE.PerspectiveCamera;
  let controls: OrbitControls;
  let points: THREE.Points | null = null;
  let colours: Float32Array;
  let index: number[] = []; // which LED each point is
  let seq = -1;
  let stopped = false;
  let raf = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const scene = new THREE.Scene();

  /** A soft round dot, so points look like LEDs, not squares. */
  function dot(): THREE.Texture {
    const c = document.createElement("canvas");
    c.width = c.height = 64;
    const g = c.getContext("2d")!;
    const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.35, "rgba(255,255,255,0.9)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, 64, 64);
    return new THREE.CanvasTexture(c);
  }

  function build(m: MapInfo) {
    if (points) {
      scene.remove(points);
      points.geometry.dispose();
    }
    index = [];
    const xyz: number[] = [];
    m.positions.forEach((p, i) => {
      if (p) {
        index.push(i);
        xyz.push(p[0], p[1], p[2]);
      }
    });
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.Float32BufferAttribute(xyz, 3));
    colours = new Float32Array(index.length * 3).fill(UNLIT);
    geom.setAttribute("color", new THREE.BufferAttribute(colours, 3));
    geom.computeBoundingSphere();
    points = new THREE.Points(geom, new THREE.PointsMaterial({
      size: 0.035, sizeAttenuation: true, vertexColors: true, map: dot(), transparent: true,
      depthWrite: false, blending: THREE.AdditiveBlending,
    }));
    scene.add(points);
    // frame it: a tree from the side, a flat layout face on
    const s = geom.boundingSphere!;
    controls.target.copy(s.center);
    const r = Math.max(s.radius, 0.2);
    const dist = r / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.05;
    camera.position.set(s.center.x, s.center.y + (m.shape === "flat" ? 0 : r * 0.25), s.center.z + dist);
    camera.near = dist / 100;
    camera.far = dist * 10;
    camera.updateProjectionMatrix();
    controls.update();
    seq = -1;
  }

  function paint(rgb: Uint8Array) {
    if (!points) return;
    const inv = 1 / gamma; // the frames are gamma-corrected for LEDs: undo that for a screen
    for (let k = 0; k < index.length; k++) {
      const o = index[k] * 3;
      for (let c = 0; c < 3; c++) colours[k * 3 + c] = Math.max(UNLIT, Math.pow((rgb[o + c] ?? 0) / 255, inv));
    }
    (points.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
  }

  async function fetchFrame() {
    if (stopped) return;
    if (!document.hidden) {
      try {
        const f = await dev.frame();
        if (f.seq !== seq) {
          seq = f.seq;
          paint(Uint8Array.from(atob(f.rgb), (ch) => ch.charCodeAt(0)));
        }
      } catch {
        /* the device page shows what's wrong */
      }
    }
    timer = setTimeout(fetchFrame, FRAME_MS);
  }

  function resize() {
    const w = host.clientWidth, h = host.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / Math.max(h, 1);
    camera.updateProjectionMatrix();
  }

  function loop() {
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  }

  let observer: ResizeObserver;
  onMount(() => {
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setClearColor(0x0b0e13);
    host.appendChild(renderer.domElement);
    camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();
    built = map;
    build(map);
    loop();
    void fetchFrame();
  });

  // a new scan, a fix or a new front: rebuild
  let built: MapInfo | null = null;
  $effect(() => {
    if (renderer && map !== built) {
      built = map;
      build(map);
    }
  });

  onDestroy(() => {
    stopped = true;
    clearTimeout(timer);
    cancelAnimationFrame(raf);
    observer?.disconnect();
    controls?.dispose();
    renderer?.dispose();
  });
</script>

<div class="view" bind:this={host}></div>

<style>
  .view { position: absolute; inset: 0; }
  .view :global(canvas) { display: block; width: 100%; height: 100%; }
</style>
