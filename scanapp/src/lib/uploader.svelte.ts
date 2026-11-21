// Films the camera track and uploads the frames to `POST /scan/frames`: a worker encodes
// JPEGs and hands over a batch every 250 ms; the page POSTs it (see encoder.worker.ts).

import type { Api } from "./api";
import type { FromWorker, ToWorker } from "./encoder.worker";
import Encoder from "./encoder.worker?worker";

const MAX_POSTS = 3; // batches in flight; one beyond that is dropped
const QUALITY = 0.8;

declare const MediaStreamTrackProcessor: {
  new (init: { track: MediaStreamTrack }): { readable: ReadableStream<VideoFrame> };
} | undefined;

export class Uploader {
  // For the page: what's been sent, and whether it's getting through.
  sent = $state(0);
  fps = $state(0);
  failed = $state(0);
  dropped = $state(0);
  error = $state<string | null>(null);
  running = $state(false);

  private worker: Worker | null = null;
  private clone: MediaStreamTrack | null = null;
  private posts = 0;
  private window: { at: number; frames: number }[] = [];
  private grabbing = false;
  private stopped: (() => void) | null = null;

  constructor(private api: Api) {}

  start(track: MediaStreamTrack, video: HTMLVideoElement): void {
    if (this.running) return;
    this.running = true;
    this.error = null;
    this.worker ??= this.makeWorker();
    if (typeof MediaStreamTrackProcessor !== "undefined") {
      // Cancelling the processor may end its track: keep the preview's own track alive.
      this.clone = track.clone();
      const { readable } = new MediaStreamTrackProcessor({ track: this.clone });
      this.send({ type: "start", quality: QUALITY, readable }, [readable as unknown as Transferable]);
    } else {
      this.send({ type: "start", quality: QUALITY });
      this.grab(video);
    }
  }

  async stop(): Promise<void> {
    if (!this.running || !this.worker) return;
    this.running = false;
    this.grabbing = false;
    const done = new Promise<void>((r) => (this.stopped = r));
    this.send({ type: "stop" });
    await Promise.race([done, new Promise((r) => setTimeout(r, 2000))]);
    this.clone?.stop();
    this.clone = null;
    this.fps = 0;
  }

  dispose(): void {
    void this.stop().then(() => {
      this.worker?.terminate();
      this.worker = null;
    });
  }

  private send(m: ToWorker, transfer: Transferable[] = []): void {
    this.worker!.postMessage(m, transfer);
  }

  private makeWorker(): Worker {
    const w = new Encoder();
    w.onmessage = (ev: MessageEvent<FromWorker>) => {
      const m = ev.data;
      if (m.type === "batch") void this.post(m.body, m.frames);
      else if (m.type === "stats") this.dropped = m.dropped;
      else if (m.type === "stopped") this.stopped?.();
    };
    return w;
  }

  /** Without MediaStreamTrackProcessor: grab each frame the <video> shows. */
  private grab(video: HTMLVideoElement): void {
    this.grabbing = true;
    const next = (_now: number, meta: VideoFrameCallbackMetadata) => {
      if (!this.grabbing) return;
      video.requestVideoFrameCallback(next);
      createImageBitmap(video).then((bitmap) => {
        const t = (meta.captureTime ?? meta.expectedDisplayTime) / 1000;
        this.send({ type: "bitmap", bitmap, t }, [bitmap]);
      }, () => {});
    };
    video.requestVideoFrameCallback(next);
  }

  private async post(body: ArrayBuffer, frames: number): Promise<void> {
    if (this.posts >= MAX_POSTS) {
      this.dropped += frames;
      return;
    }
    this.posts++;
    try {
      await this.api.frames(body);
      this.sent += frames;
      this.error = null;
      const now = performance.now();
      this.window.push({ at: now, frames });
      this.window = this.window.filter((x) => now - x.at < 2000);
      this.fps = Math.round(this.window.reduce((n, x) => n + x.frames, 0) / 2);
    } catch (e) {
      this.failed += frames;
      this.error = (e as Error).message;
    } finally {
      this.posts--;
    }
  }
}
