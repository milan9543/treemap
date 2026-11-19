// The /ws/viewer connection: LED frames in, JSON messages both ways.
import { app } from "./state.svelte";

type Handler = (msg: any) => void;

const handlers = new Map<string, Handler[]>();
const pending = new Map<number, { reply: string; resolve: (reply: any) => void }>();
let ws: WebSocket | null = null;
let requestId = 0;
let onFrame: (buf: ArrayBuffer) => void = () => {};

export const NOT_CONNECTED = "Not connected to the server. Is `treemap sim view` running?";

export function on(type: string, fn: Handler): void {
  if (!handlers.has(type)) handlers.set(type, []);
  handlers.get(type)!.push(fn);
}

export function onLedFrame(fn: (buf: ArrayBuffer) => void): void {
  onFrame = fn;
}

export const connected = () => ws !== null && ws.readyState === WebSocket.OPEN;

/** Send a JSON message; false if not connected. */
export function send(msg: object): boolean {
  if (!connected()) return false;
  ws!.send(JSON.stringify(msg));
  return true;
}

/** Send ``{type, id, ...}`` and resolve with the ``reply``-typed message carrying the same id. */
export function request(type: string, reply: string, body: object): Promise<any> {
  if (!connected()) return Promise.resolve({ ok: false, error: NOT_CONNECTED });
  const id = ++requestId;
  return new Promise((resolve) => {
    pending.set(id, { reply, resolve });
    ws!.send(JSON.stringify({ type, id, ...body }));
  });
}

export function connect(): void {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/viewer`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => { app.connected = true; };
  ws.onclose = () => {
    app.connected = false;
    for (const p of pending.values()) p.resolve({ ok: false, error: "lost connection to the server" });
    pending.clear();
    setTimeout(connect, 1000);
  };
  ws.onmessage = (ev) => {
    if (typeof ev.data !== "string") {
      onFrame(ev.data as ArrayBuffer);
      return;
    }
    const msg = JSON.parse(ev.data);
    const p = pending.get(msg.id);
    if (p && p.reply === msg.type) {
      p.resolve(msg);
      pending.delete(msg.id);
      return;
    }
    for (const fn of handlers.get(msg.type) ?? []) fn(msg);
  };
}
