"""Phase 1 spike server: the LAN end of the HTTPS test page (PLAN-2.0.md, steps 1.1-1.3).

Throwaway. Standard library plus the project's own frame decoder, so run it with

    uv run python spikes/phase1/server.py [--port 8765]

Endpoints (all answer CORS for any origin, and Chrome's local-network preflight):

    GET  /ping     {"ok": true, ...}                                   (1.1)
    POST /report   the page's JSON report, saved to spikes/phase1/out/ (1.2, 1.3)
    POST /frames   a batch of frames, application/octet-stream        (1.3)
    GET  /stats    what /frames has received in the last few seconds
    GET  /         the page itself over plain HTTP, for desktop testing on localhost

Batch format for /frames: frames back to back, each one a 4-byte little-endian length
followed by exactly what ``treemap.cameras.browser.pack_frame`` makes today (4-byte
header length, JSON header with ``t``, JPEG). So the existing ``unpack_frame`` reads
each frame unchanged.
"""

from __future__ import annotations

import argparse
import collections
import json
import socket
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "page"
OUT = ROOT / "out"
sys.path.insert(0, str(ROOT.parents[1]))
from treemap.cameras.browser import unpack_frame  # noqa: E402

PAGE_URL = "https://treemap-spike.pages.dev/"
WINDOW = 3.0  # s of history behind /stats


class Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events: collections.deque[tuple[float, int, int]] = collections.deque()  # (t, frames, bytes)
        self.total_frames = 0
        self.bad_frames = 0
        self.last_shape: tuple[int, ...] | None = None
        self.last_header: dict | None = None
        self.decode_ms: collections.deque[float] = collections.deque(maxlen=200)
        self.saved: set[tuple[int, ...]] = set()

    def add(self, frames: int, nbytes: int) -> None:
        now = time.monotonic()
        with self.lock:
            self.events.append((now, frames, nbytes))
            self.total_frames += frames
            while self.events and self.events[0][0] < now - WINDOW:
                self.events.popleft()

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self.lock:
            ev = [e for e in self.events if e[0] >= now - WINDOW]
            span = (now - ev[0][0]) if len(ev) > 1 else WINDOW
            frames = sum(e[1] for e in ev)
            nbytes = sum(e[2] for e in ev)
            dec = sorted(self.decode_ms)
            return {
                "fps": round(frames / max(span, 0.25), 1),
                "mb_per_s": round(nbytes / max(span, 0.25) / 1e6, 2),
                "batches_per_s": round(len(ev) / max(span, 0.25), 1),
                "total_frames": self.total_frames,
                "bad_frames": self.bad_frames,
                "last_shape": self.last_shape,
                "last_header": self.last_header,
                "decode_ms_median": round(dec[len(dec) // 2], 1) if dec else None,
            }


STATS = Stats()


def split_batch(body: bytes) -> list[bytes]:
    out, i = [], 0
    while i + 4 <= len(body):
        (n,) = struct.unpack_from("<I", body, i)
        i += 4
        if n <= 0 or i + n > len(body):
            raise ValueError(f"frame length {n} runs past the batch end")
        out.append(body[i:i + n])
        i += n
    if i != len(body):
        raise ValueError("trailing bytes after the last frame")
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "treemap-spike/0"
    protocol_version = "HTTP/1.1"  # keep-alive: a batch every 250 ms shouldn't open a connection each time

    def log_message(self, fmt: str, *args) -> None:  # quiet: /frames arrives 4x a second
        if not self.path.startswith(("/frames", "/stats")):
            sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        # The older Private Network Access preflight; harmless under Local Network Access.
        if self.headers.get("Access-Control-Request-Private-Network"):
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode())

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/ping":
            self._json({"ok": True, "server": "treemap-spike", "time": time.time(),
                        "origin": self.headers.get("Origin")})
        elif path == "/stats":
            self._json(STATS.snapshot())
        elif path in ("/", "/index.html", "/worker.js"):
            f = PAGE / ("index.html" if path == "/" else path.lstrip("/"))
            ctype = "text/html" if f.suffix == ".html" else "text/javascript"
            self._send(200, f.read_bytes(), f"{ctype}; charset=utf-8")
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        if path == "/frames":
            self._frames()
        elif path == "/report":
            body = self._body()
            try:
                report = json.loads(body)
            except json.JSONDecodeError:
                return self._json({"error": "not JSON"}, 400)
            OUT.mkdir(exist_ok=True)
            f = OUT / f"report-{time.strftime('%Y%m%d-%H%M%S')}.json"
            f.write_text(json.dumps(report, indent=2))
            print(f"saved {f.relative_to(ROOT.parents[1])}", flush=True)
            self._json({"ok": True, "saved": f.name})
        else:
            self._json({"error": "not found"}, 404)

    def _frames(self) -> None:
        body = self._body()
        try:
            frames = split_batch(body)
        except (ValueError, struct.error) as e:
            return self._json({"error": str(e)}, 400)
        decoded = 0
        for i, data in enumerate(frames):
            # Decode every frame: proves the format, and the decode cost is part of the test.
            t0 = time.perf_counter()
            try:
                frame = unpack_frame(data)
            except Exception as e:  # noqa: BLE001 - spike: count and carry on
                with STATS.lock:
                    STATS.bad_frames += 1
                print(f"bad frame: {e}", flush=True)
                continue
            dt = (time.perf_counter() - t0) * 1000
            decoded += 1
            with STATS.lock:
                STATS.decode_ms.append(dt)
                STATS.last_shape = frame.image.shape
                STATS.last_header = {"t": frame.t, **frame.meta}
                first = frame.image.shape not in STATS.saved
                STATS.saved.add(frame.image.shape)
            if first:  # keep one sample per size, to look at
                import cv2
                OUT.mkdir(exist_ok=True)
                h, w = frame.image.shape[:2]
                cv2.imwrite(str(OUT / f"sample-{w}x{h}.jpg"), frame.image)
        STATS.add(decoded, len(body))
        self._json({"ok": True, "frames": decoded, "bytes": len(body)})


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the LAN interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    ip = lan_ip()
    server = f"http://{ip}:{args.port}"
    print(f"spike server on {server}")
    print(f"open on the phone:  {PAGE_URL}?server={server}")
    print(f"or on this Mac:     http://localhost:{args.port}/?server=http://localhost:{args.port}")

    def ticker() -> None:
        last = -1
        while True:
            time.sleep(1)
            s = STATS.snapshot()
            if s["total_frames"] != last:
                last = s["total_frames"]
                print(f"  frames: {s['fps']:5.1f} fps  {s['mb_per_s']:5.2f} MB/s  "
                      f"{s['batches_per_s']:.1f} batches/s  shape {s['last_shape']}  "
                      f"decode {s['decode_ms_median']} ms  bad {s['bad_frames']}", flush=True)

    threading.Thread(target=ticker, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
