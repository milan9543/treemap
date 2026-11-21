// Phase 1 spike, step 1.3: encode camera frames to JPEG off the main thread and POST
// them to the server in batches. Throwaway.
//
// Frames come in one of two ways:
//   "readable": a MediaStreamTrackProcessor's stream of VideoFrames, transferred here
//   "bitmap":   ImageBitmaps the main thread grabs on each requestVideoFrameCallback
//
// Wire format of a batch: per frame, a u32 LE length, then the frame exactly as
// treemap.cameras.browser.pack_frame makes it (u32 LE header length, JSON header, JPEG).

const MAX_ENCODING = 2; // frames being encoded at once; more arriving are dropped
const MAX_POSTS = 3; // batches in flight; a batch beyond that is dropped

let cfg = null;
let canvas = null;
let ctx = null;
let reader = null;
let timer = null;
let statTimer = null;
let encoding = 0;
let posts = 0;
let batch = [];
let s = null; // totals for this run
let last = null; // totals at the previous live tick
let postId = 0;
const postWaiters = new Map(); // batch id -> resolve, when the page does the POST

// One fetch from inside the worker, so the page can compare it with the same fetch of its own.
async function probe(m) {
  const t0 = performance.now();
  const r = { method: m.method };
  try {
    const opts = { method: m.method, cache: "no-store" };
    if (m.method === "POST") {
      opts.body = new Uint8Array(0);
      opts.headers = { "Content-Type": "application/octet-stream" };
    }
    if (m.tas) opts.targetAddressSpace = "local";
    const res = await fetch(m.url, opts);
    r.status = res.status;
    r.ok = res.ok;
  } catch (e) {
    r.ok = false;
    r.error = String(e);
  }
  r.ms = Math.round(performance.now() - t0);
  self.postMessage({ type: "probe", id: m.id, result: r });
}

function fresh() {
  return {
    t0: performance.now(), framesIn: 0, encoded: 0, dropped: 0, jpegBytes: 0,
    bytesSent: 0, postsOk: 0, postsFailed: 0, batchesDropped: 0,
    encodeMs: [], postMs: [], lastError: null, index: 0,
  };
}

const median = (a) => {
  if (!a.length) return null;
  const b = [...a].sort((x, y) => x - y);
  return Math.round(b[b.length >> 1] * 10) / 10;
};

function summary(now, from, base) {
  const sec = Math.max((now - from) / 1000, 0.001);
  const d = (k) => s[k] - (base ? base[k] : 0);
  return {
    seconds: Math.round(sec * 10) / 10,
    camFps: +(d("framesIn") / sec).toFixed(1),
    encFps: +(d("encoded") / sec).toFixed(1),
    dropped: d("dropped"),
    jpegKB: s.encoded ? Math.round(s.jpegBytes / s.encoded / 1024) : null,
    uploadMBs: +(d("bytesSent") / sec / 1e6).toFixed(2),
    encodeMsMedian: median(s.encodeMs.slice(-100)),
    postMsMedian: median(s.postMs.slice(-40)),
    postsOk: s.postsOk, postsFailed: s.postsFailed, batchesDropped: s.batchesDropped,
    inflight: posts, lastError: s.lastError,
  };
}

async function encode(source, t, width, height) {
  if (encoding >= MAX_ENCODING) {
    s.dropped++;
    source.close();
    return;
  }
  encoding++;
  const t0 = performance.now();
  try {
    const w = cfg.width || width, h = cfg.height || height;
    if (!canvas || canvas.width !== w || canvas.height !== h) {
      canvas = new OffscreenCanvas(w, h);
      ctx = canvas.getContext("2d", { alpha: false });
    }
    ctx.drawImage(source, 0, 0, w, h);
    source.close(); // the canvas has it now; give the camera its buffer back
    // convertToBlob snapshots the canvas now, so the next frame may draw while this encodes.
    const blob = await canvas.convertToBlob({ type: "image/jpeg", quality: cfg.quality });
    const jpeg = new Uint8Array(await blob.arrayBuffer());
    const header = new TextEncoder().encode(JSON.stringify({ t, i: s.index++, w, h }));
    const frame = new Uint8Array(8 + header.length + jpeg.length);
    const dv = new DataView(frame.buffer);
    dv.setUint32(0, 4 + header.length + jpeg.length, true);
    dv.setUint32(4, header.length, true);
    frame.set(header, 8);
    frame.set(jpeg, 8 + header.length);
    batch.push(frame);
    s.encoded++;
    s.jpegBytes += jpeg.length;
    s.encodeMs.push(performance.now() - t0);
  } catch (e) {
    s.lastError = "encode: " + e;
    try { source.close(); } catch {}
  } finally {
    encoding--;
  }
}

async function flush() {
  if (!batch.length) return;
  const frames = batch;
  batch = [];
  if (posts >= MAX_POSTS) {
    s.batchesDropped++;
    return;
  }
  let n = 0;
  for (const f of frames) n += f.length;
  const body = new Uint8Array(n);
  let o = 0;
  for (const f of frames) { body.set(f, o); o += f.length; }
  posts++;
  const t0 = performance.now();
  try {
    if (cfg.postFrom === "main") {
      // Hand the batch to the page, which POSTs it (a worker may lack the local network permission).
      const id = ++postId;
      const done = new Promise((r) => postWaiters.set(id, r));
      self.postMessage({ type: "batch", id, body: body.buffer }, [body.buffer]);
      const res = await done;
      if (!res.ok) throw new Error(res.error);
    } else {
      const opts = { method: "POST", body, headers: { "Content-Type": "application/octet-stream" } };
      if (cfg.targetAddressSpace) opts.targetAddressSpace = "local";
      const r = await fetch(cfg.server + "/frames", opts);
      if (!r.ok) throw new Error("HTTP " + r.status + " " + (await r.text()));
    }
    s.postsOk++;
    s.bytesSent += n;
    s.postMs.push(performance.now() - t0);
  } catch (e) {
    s.postsFailed++;
    s.lastError = "post: " + e;
  } finally {
    posts--;
  }
}

async function pump(readable) {
  reader = readable.getReader();
  for (;;) {
    let r;
    try { r = await reader.read(); } catch { break; }
    if (r.done) break;
    const vf = r.value;
    if (!cfg) { vf.close(); continue; }
    s.framesIn++;
    encode(vf, (performance.timeOrigin + performance.now()) / 1000, vf.displayWidth, vf.displayHeight);
  }
}

async function stop() {
  clearInterval(timer);
  clearInterval(statTimer);
  if (reader) { try { await reader.cancel(); } catch {} reader = null; }
  while (encoding > 0) await new Promise((r) => setTimeout(r, 20));
  await flush();
  while (posts > 0) await new Promise((r) => setTimeout(r, 20));
  const result = summary(performance.now(), s.t0, null);
  cfg = null;
  return result;
}

self.onmessage = async (ev) => {
  const m = ev.data;
  if (m.type === "start") {
    cfg = m.cfg;
    s = fresh();
    last = { ...s, at: performance.now() };
    batch = [];
    timer = setInterval(flush, cfg.batchMs);
    statTimer = setInterval(() => {
      const now = performance.now();
      self.postMessage({ type: "live", stats: summary(now, last.at, last) });
      last = { ...s, at: now };
    }, 1000);
    if (m.readable) pump(m.readable);
  } else if (m.type === "bitmap") {
    if (!cfg) { m.bitmap.close(); return; }
    s.framesIn++;
    encode(m.bitmap, m.t, m.bitmap.width, m.bitmap.height);
  } else if (m.type === "posted") {
    postWaiters.get(m.id)?.(m);
    postWaiters.delete(m.id);
  } else if (m.type === "probe") {
    probe(m);
  } else if (m.type === "stop") {
    const result = cfg ? await stop() : null;
    self.postMessage({ type: "done", stats: result });
  }
};
