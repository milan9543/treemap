// Encodes camera frames to JPEG off the main thread and hands the page a batch every
// 250 ms, for it to POST (a worker's own fetches to the LAN fail: spike 1.1).
//
// Frames arrive either as a MediaStreamTrackProcessor's stream of VideoFrames
// ("start" with `readable`) or as ImageBitmaps the page grabs ("bitmap").
//
// A batch is, per frame: a u32 LE length, then exactly what
// treemap.cameras.browser.pack_frame makes (u32 LE header length, JSON header, JPEG).

/// <reference lib="webworker" />
declare const self: DedicatedWorkerGlobalScope;

const MAX_ENCODING = 2; // frames being encoded at once; more arriving are dropped
const BATCH_MS = 250;

export type ToWorker =
  | { type: "start"; quality: number; readable?: ReadableStream<VideoFrame> }
  | { type: "bitmap"; bitmap: ImageBitmap; t: number }
  | { type: "stop" };

export type FromWorker =
  | { type: "batch"; body: ArrayBuffer; frames: number }
  | { type: "stats"; encoded: number; dropped: number; encodeMs: number | null }
  | { type: "stopped" };

let quality = 0.8;
let running = false;
let canvas: OffscreenCanvas | null = null;
let ctx: OffscreenCanvasRenderingContext2D | null = null;
let reader: ReadableStreamDefaultReader<VideoFrame> | null = null;
let timer: ReturnType<typeof setInterval> | undefined;
let encoding = 0;
let index = 0;
let batch: Uint8Array[] = [];
let encoded = 0;
let dropped = 0;
let encodeMs: number[] = [];
const header = new TextEncoder();

async function encode(source: VideoFrame | ImageBitmap, t: number): Promise<void> {
  if (!running || encoding >= MAX_ENCODING) {
    dropped += running ? 1 : 0;
    source.close();
    return;
  }
  encoding++;
  const t0 = performance.now();
  try {
    const w = "displayWidth" in source ? source.displayWidth : source.width;
    const h = "displayHeight" in source ? source.displayHeight : source.height;
    if (!canvas || canvas.width !== w || canvas.height !== h) {
      canvas = new OffscreenCanvas(w, h);
      ctx = canvas.getContext("2d", { alpha: false });
    }
    ctx!.drawImage(source, 0, 0, w, h);
    source.close(); // give the camera its buffer back
    // convertToBlob snapshots the canvas now, so the next frame may draw while this encodes.
    const blob = await canvas.convertToBlob({ type: "image/jpeg", quality });
    const jpeg = new Uint8Array(await blob.arrayBuffer());
    const head = header.encode(JSON.stringify({ t, i: index++, w, h }));
    const frame = new Uint8Array(8 + head.length + jpeg.length);
    const dv = new DataView(frame.buffer);
    dv.setUint32(0, 4 + head.length + jpeg.length, true);
    dv.setUint32(4, head.length, true);
    frame.set(head, 8);
    frame.set(jpeg, 8 + head.length);
    batch.push(frame);
    encoded++;
    encodeMs.push(performance.now() - t0);
  } catch {
    try {
      source.close();
    } catch {
      /* already closed */
    }
  } finally {
    encoding--;
  }
}

function flush(): void {
  if (batch.length) {
    const frames = batch;
    batch = [];
    const body = new Uint8Array(frames.reduce((n, f) => n + f.length, 0));
    let o = 0;
    for (const f of frames) {
      body.set(f, o);
      o += f.length;
    }
    post({ type: "batch", body: body.buffer, frames: frames.length }, [body.buffer]);
  }
  const sorted = encodeMs.sort((a, b) => a - b);
  post({ type: "stats", encoded, dropped,
         encodeMs: sorted.length ? Math.round(sorted[sorted.length >> 1]) : null });
  encodeMs = [];
}

function post(m: FromWorker, transfer: Transferable[] = []): void {
  self.postMessage(m, transfer);
}

async function pump(readable: ReadableStream<VideoFrame>): Promise<void> {
  reader = readable.getReader();
  for (;;) {
    let r: ReadableStreamReadResult<VideoFrame>;
    try {
      r = await reader.read();
    } catch {
      break;
    }
    if (r.done) break;
    // The capture time (µs) beats the time it reached the worker.
    void encode(r.value, r.value.timestamp / 1e6);
  }
}

self.onmessage = async (ev: MessageEvent<ToWorker>) => {
  const m = ev.data;
  if (m.type === "start") {
    quality = m.quality;
    running = true;
    batch = [];
    encoded = dropped = 0;
    clearInterval(timer);
    timer = setInterval(flush, BATCH_MS);
    if (m.readable) void pump(m.readable);
  } else if (m.type === "bitmap") {
    void encode(m.bitmap, m.t);
  } else if (m.type === "stop") {
    running = false;
    clearInterval(timer);
    if (reader) {
      try {
        await reader.cancel();
      } catch {
        /* already done */
      }
      reader = null;
    }
    while (encoding > 0) await new Promise((r) => setTimeout(r, 20));
    flush();
    post({ type: "stopped" });
  }
};
