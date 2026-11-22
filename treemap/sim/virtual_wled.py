"""A virtual WLED controller: a simulated tree (or flat layout) on this computer's screen,
driven over the network exactly like the real LEDs.

``treemap sim wled`` runs it. Configure ``treemap serve`` with it as its controller
(``controllers: [{host: <this computer's IP>:<port>}]``, ``output: wled``) and the server
can't tell it from real hardware: it reads the LED count from ``/json/info`` and streams
colours over DDP. The page shows them on the 3D layout, which turns (by dragging, or by
itself) or which you walk round, while the phone films the screen. So the whole 2.0 path is tested: phone
page, server, DDP, LEDs, camera.

Network:
    UDP ``ddp_port`` (4048, as WLED)  DDP frames, assembled and shown on each push flag
    HTTP, one port:
        /             the page (viewer/wled.html, built into treemap/sim/viewer_dist)
        /assets/*     its scripts and styles
        /json, /json/info, /json/state, /json/cfg
                      the parts of WLED's JSON API that treemap reads
        /api/layout   the layout: a tree (as sim_tree.json) or a flat one, with "shape"
    Websocket ``/ws``: the page receives LED frames (binary, led_count × RGB) and JSON
        ``{"type": "status", ...}`` once a second and ``{"type": "layout"}`` when the layout
        changes. It may send ``{"type": "generate", "id", "shape", "spec"}`` for a new
        layout and gets ``{"type": "generated", "id", "ok", "error"?}`` back.

Like WLED, it drops back to dark when frames stop for ``REALTIME_TIMEOUT_S``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import socket
import struct
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from websockets.asyncio.server import ServerConnection, broadcast, serve
from websockets.http11 import Request, Response

from treemap.sim.flat import FlatSpec, SimFlat, generate_flat
from treemap.sim.server import CONTENT_TYPES, _response, viewer_dir
from treemap.sim.tree import SimTree, SpecError, TreeSpec, generate_tree

log = logging.getLogger(__name__)

DDP_PORT = 4048
HTTP_PORT = 8780
REALTIME_TIMEOUT_S = 2.5  # WLED's default: back to its own effect (here: dark) after this
SHAPES = ("tree", "flat")
NOT_BUILT = b"""<!doctype html><meta charset="utf-8"><title>virtual WLED</title>
<body style="font: 15px system-ui; background: #07090d; color: #d8dee9; padding: 2em">
<h1>The page isn't built yet</h1>
<p>Run <code>npm --prefix viewer install && npm --prefix viewer run build</code> in the
project folder, then reload this page.</p>"""


# -- layouts ------------------------------------------------------------------------------

Layout = SimTree | SimFlat


def load_layout(path: Path) -> Layout:
    d = json.loads(path.read_text())
    return SimFlat.from_dict(d) if d.get("shape") == "flat" else SimTree.from_dict(d)


def new_layout(shape: str, spec: dict[str, Any] | None = None) -> Layout:
    """A new tree or flat layout from a spec (JSON-like, as the page sends). Raises
    :class:`SpecError`."""
    if shape not in SHAPES:
        raise SpecError(f"shape must be one of {', '.join(SHAPES)}")
    if shape == "flat":
        return generate_flat(FlatSpec.from_dict(spec or {}))
    return generate_tree(TreeSpec.from_dict(spec or {}))


def layout_dict(layout: Layout) -> dict[str, Any]:
    return {**layout.to_dict(), "shape": "flat" if isinstance(layout, SimFlat) else "tree"}


# -- DDP ----------------------------------------------------------------------------------


class DdpFrames:
    """Assembles DDP packets into frames of RGB bytes."""

    def __init__(self, led_count: int) -> None:
        self.buffer = bytearray(led_count * 3)

    def resize(self, led_count: int) -> None:
        self.buffer = bytearray(led_count * 3)

    def add(self, packet: bytes) -> bytes | None:
        """Take one packet; returns the frame when the packet pushes it (else None)."""
        if len(packet) < 10:
            return None
        flags = packet[0]
        if flags & 0xC0 != 0x40:  # DDP version 1 only
            return None
        header = 14 if flags & 0x10 else 10  # a timecode adds 4 bytes
        (offset,) = struct.unpack_from(">I", packet, 4)
        (length,) = struct.unpack_from(">H", packet, 8)
        data = packet[header:header + length]
        end = min(offset + len(data), len(self.buffer))
        if offset < end:
            self.buffer[offset:end] = data[:end - offset]
        return bytes(self.buffer) if flags & 0x01 else None


# -- the controller -----------------------------------------------------------------------


@dataclass
class VirtualWled:
    layout_path: Path
    host: str = "0.0.0.0"
    port: int = HTTP_PORT
    ddp_port: int = DDP_PORT
    address: str = "127.0.0.1"  # how the server reaches us, for the config line we print

    layout: Layout | None = field(default=None, init=False)
    clients: set[ServerConnection] = field(default_factory=set, init=False)
    last_frame: bytes | None = field(default=None, init=False)
    source: str | None = field(default=None, init=False)  # who sends the DDP
    _frames: DdpFrames = field(default_factory=lambda: DdpFrames(0), init=False)
    _times: deque = field(default_factory=lambda: deque(maxlen=120), init=False)
    _last_at: float = field(default=0.0, init=False)
    _live: bool = field(default=False, init=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False)
    _sock: socket.socket | None = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def led_count(self) -> int:
        return self.layout.led_count if self.layout is not None else 0

    def use(self, layout: Layout) -> None:
        self.layout = layout
        self._frames.resize(layout.led_count)
        self.last_frame = None

    @property
    def controller_line(self) -> str:
        return f"controllers: [{{host: \"{self.address}:{self.port}\"}}]"

    # -- WLED's JSON API ----------------------------------------------------------------

    def fps(self) -> float:
        now = time.monotonic()
        recent = [t for t in self._times if now - t < 2.0]
        return round(len(recent) / 2.0, 1)

    def info(self) -> dict[str, Any]:
        return {
            "ver": "0.15.0", "vid": 2412040, "name": "treemap virtual WLED",
            "leds": {"count": self.led_count, "rgbw": False, "wv": 0, "cct": 0,
                     "fps": self.fps(), "pwr": 0, "maxpwr": 0},
            "live": self._live, "lm": "DDP" if self._live else "", "lip": self.source or "",
            "udpport": 21324, "brand": "WLED", "product": "treemap virtual", "arch": "virtual",
            "mac": "000000000000", "ip": self.address,
        }

    def state(self) -> dict[str, Any]:
        return {"on": True, "bri": 255, "transition": 7, "ps": -1, "pl": -1, "live": self._live,
                "seg": [{"id": 0, "start": 0, "stop": self.led_count, "on": True, "bri": 255}]}

    def cfg(self) -> dict[str, Any]:
        return {"wifi": {"sleep": False}, "hw": {"led": {"total": self.led_count}},
                "if": {"live": {"en": True, "port": 5568, "timeout": int(REALTIME_TIMEOUT_S * 10)}}}

    def status(self) -> dict[str, Any]:
        return {"type": "status", "led_count": self.led_count, "live": self._live,
                "fps": self.fps(), "source": self.source, "controller": self.controller_line,
                "shape": "flat" if isinstance(self.layout, SimFlat) else "tree"}

    # -- HTTP ---------------------------------------------------------------------------

    def process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None
        path = urlsplit(request.path).path.rstrip("/") or "/"
        if path in ("/", "/index.html"):
            page = viewer_dir().joinpath("wled.html")
            html = page.read_bytes() if page.is_file() else NOT_BUILT
            return _response(HTTPStatus.OK, html, "text/html; charset=utf-8")
        if path.startswith("/assets/"):
            name = path.removeprefix("/assets/")
            asset = viewer_dir().joinpath("assets", name)
            if re.fullmatch(r"[\w.-]+", name) and asset.is_file():
                kind = CONTENT_TYPES.get(Path(name).suffix, "application/octet-stream")
                return _response(HTTPStatus.OK, asset.read_bytes(), kind)
        routes: dict[str, Callable[[], Any]] = {
            "/json": lambda: {"state": self.state(), "info": self.info(), "effects": ["Solid"],
                              "palettes": ["Default"]},
            "/json/info": self.info,
            "/json/state": self.state,
            "/json/si": lambda: {"state": self.state(), "info": self.info()},
            "/json/cfg": self.cfg,
            "/api/layout": lambda: layout_dict(self.layout) if self.layout else None,
        }
        if path in routes:
            body = routes[path]()
            if body is None:
                return _response(HTTPStatus.NOT_FOUND, b'{"error": "no layout"}', "application/json")
            return _response(HTTPStatus.OK, json.dumps(body, separators=(",", ":")).encode(),
                             "application/json")
        return _response(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")

    # -- websocket ----------------------------------------------------------------------

    async def handler(self, ws: ServerConnection) -> None:
        if (urlsplit(ws.request.path).path if ws.request else "") != "/ws":
            await ws.close(code=1008, reason="unknown endpoint")
            return
        self.clients.add(ws)
        try:
            await ws.send(json.dumps(self.status()))
            if self.last_frame is not None:
                await ws.send(self.last_frame)
            async for message in ws:
                if isinstance(message, str):
                    await self._message(ws, message)
        finally:
            self.clients.discard(ws)

    async def _message(self, ws: ServerConnection, message: str) -> None:
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, dict) or msg.get("type") != "generate":
            return
        reply: dict[str, Any] = {"type": "generated", "id": msg.get("id")}
        async with self._lock:
            try:
                layout = await asyncio.to_thread(new_layout, str(msg.get("shape")), msg.get("spec"))
                await asyncio.to_thread(layout.save, self.layout_path)
            except SpecError as e:
                reply.update(ok=False, error=str(e))
            else:
                self.use(layout)
                reply.update(ok=True, led_count=layout.led_count)
                broadcast(self.clients, json.dumps({"type": "layout"}))
                broadcast(self.clients, json.dumps(self.status()))
        with contextlib.suppress(Exception):
            await ws.send(json.dumps(reply))

    # -- DDP (a thread of its own) ------------------------------------------------------

    def _receive(self) -> None:
        sock = self._sock
        assert sock is not None
        while True:
            try:
                packet, addr = sock.recvfrom(65535)
            except OSError:
                return  # closed
            frame = self._frames.add(packet)
            if frame is not None and self._loop is not None:
                self._loop.call_soon_threadsafe(self._show, frame, addr[0])

    def _show(self, frame: bytes, source: str) -> None:
        now = time.monotonic()
        self._times.append(now)
        self._last_at = now
        self.last_frame = frame
        if not self._live or source != self.source:
            self._live, self.source = True, source
            broadcast(self.clients, json.dumps(self.status()))
        broadcast(self.clients, frame)

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            if self._live and time.monotonic() - self._last_at > REALTIME_TIMEOUT_S:
                self._live = False
                self.last_frame = bytes(self.led_count * 3)
                broadcast(self.clients, self.last_frame)
            broadcast(self.clients, json.dumps(self.status()))

    def open_ddp(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.ddp_port))
        self.ddp_port = sock.getsockname()[1]  # resolves port 0
        self._sock = sock

    async def serve(self, stop: asyncio.Future | None = None,
                    on_ready: Callable[[VirtualWled], None] | None = None) -> None:
        if self._sock is None:
            self.open_ddp()
        async with serve(self.handler, self.host, self.port, process_request=self.process_request,
                         compression=None) as server:
            self.port = server.sockets[0].getsockname()[1]
            self._loop = asyncio.get_running_loop()
            threading.Thread(target=self._receive, name="ddp", daemon=True).start()
            ticker = asyncio.create_task(self._tick())
            if on_ready:
                on_ready(self)
            try:
                await (stop if stop is not None else asyncio.Future())
            finally:
                ticker.cancel()
                assert self._sock is not None
                self._sock.close()
