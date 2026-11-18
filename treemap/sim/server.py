"""Local HTTP + websocket server for the 3D viewer, all on one port.

HTTP routes:
    /            the viewer page
    /api/config  led_count, the generator defaults from config.yaml and accepted ranges
    /api/tree    the simulator ground truth (sim_tree.json), 404 if not generated yet
    /api/map     the reconstructed map (tree_map.json), 404 if not scanned yet
    /api/effects the effects the engine can run, with their parameters
Websockets:
    /ws/output   producers (``SimOutput``) send binary frames of led_count × RGB bytes
    /ws/viewer   browsers receive those frames, plus JSON ``{"type": "reload"}`` messages
                 when the tree or map file changes on disk, and ``{"type": "engine"}``
                 state whenever the effects engine changes. Browsers may send:
                   {"type": "generate", "id", "spec"}  -> {"type": "generated", "id", "ok", ...}
                   {"type": "effect.run", "effect", "params"}
                   {"type": "effect.params", "params"}
                   {"type": "effect.brightness", "value"}
                   {"type": "effect.stop"}
                 Rejected effect requests get {"type": "effect.error", "error"} back.
(The websockets HTTP layer only accepts GET, hence commands go over the websocket.)

The effects engine runs in this process and sends its frames through an ordinary
``LedOutput``: the sim output loops back into ``/ws/output`` here, a WLED output goes to
the real tree, so the browser can drive either.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from importlib import resources
from pathlib import Path
from urllib.parse import urlsplit

from websockets.asyncio.server import ServerConnection, broadcast, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from treemap.effects import ParamError, describe_effects
from treemap.engine import Engine
from treemap.sim.tree import (
    HEIGHT_RANGE,
    LIMITS,
    PITCH_RANGE,
    RADIUS_RANGE,
    SpecError,
    TreeSpec,
    generate_tree,
)

log = logging.getLogger(__name__)


@dataclass
class SimServer:
    tree_path: Path
    map_path: Path
    host: str = "127.0.0.1"
    port: int = 8765
    poll_s: float = 0.5
    led_count: int = 400  # what the test patterns and effects will send
    defaults: TreeSpec = field(default_factory=TreeSpec)  # generator form defaults
    # Builds the effects engine once the port is known (the sim output loops back to it).
    # None disables effects in the viewer.
    make_engine: Callable[[SimServer], Engine] | None = None
    output_label: str = "sim"  # where the engine's frames go, shown in the viewer

    viewers: set[ServerConnection] = field(default_factory=set, init=False)
    producers: int = field(default=0, init=False)
    last_frame: bytes | None = field(default=None, init=False)
    engine: Engine | None = field(default=None, init=False)
    _generate_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False)

    # -- HTTP ---------------------------------------------------------------------------

    def process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None  # let the websocket handshake proceed
        path = urlsplit(request.path).path
        if path in ("/", "/index.html"):
            html = resources.files("treemap.sim").joinpath("viewer/index.html").read_bytes()
            return _response(HTTPStatus.OK, html, "text/html; charset=utf-8")
        if path == "/api/config":
            body = {
                "led_count": self.led_count,
                "defaults": self.defaults.to_dict(),
                "limits": LIMITS,
                "random": {"height": HEIGHT_RANGE, "radius": RADIUS_RANGE, "spacing": PITCH_RANGE},
            }
            return _response(HTTPStatus.OK, json.dumps(body).encode(), "application/json")
        if path == "/api/effects":
            body = {
                "available": self.engine is not None,
                "output": self.output_label,
                "effects": describe_effects(self.led_count),
            }
            return _response(HTTPStatus.OK, json.dumps(body).encode(), "application/json")
        if path == "/api/tree":
            return _file_response(self.tree_path, "no sim tree yet: run `treemap sim new`")
        if path == "/api/map":
            return _file_response(self.map_path, "no reconstructed map yet")
        return _response(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")

    # -- websockets ---------------------------------------------------------------------

    async def handler(self, ws: ServerConnection) -> None:
        path = urlsplit(ws.request.path).path if ws.request else ""
        if path == "/ws/viewer":
            await self._viewer(ws)
        elif path == "/ws/output":
            await self._producer(ws)
        else:
            await ws.close(code=1008, reason="unknown endpoint")

    async def _viewer(self, ws: ServerConnection) -> None:
        self.viewers.add(ws)
        log.info("viewer connected (%d open)", len(self.viewers))
        try:
            await ws.send(json.dumps({"type": "status", "producers": self.producers}))
            if self.engine is not None:
                await ws.send(json.dumps(self._engine_state()))
            if self.last_frame is not None:
                await ws.send(self.last_frame)
            async for message in ws:
                if isinstance(message, str):
                    await self._viewer_message(ws, message)
        finally:
            self.viewers.discard(ws)

    async def _viewer_message(self, ws: ServerConnection, message: str) -> None:
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "generate":
            await self._generate(ws, msg)
        elif isinstance(kind, str) and kind.startswith("effect."):
            await self._effect_command(ws, kind, msg)

    async def _effect_command(self, ws: ServerConnection, kind: str, msg: dict) -> None:
        engine = self.engine
        try:
            if engine is None:
                raise LookupError("effects are not available in this viewer")
            params = msg.get("params") or {}
            if not isinstance(params, dict):
                raise ParamError("params must be an object")
            if kind == "effect.run":
                engine.start(str(msg.get("effect")), params)
            elif kind == "effect.params":
                engine.set_params(params)
            elif kind == "effect.brightness":
                value = msg.get("value")
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("brightness must be a number 0-1")
                engine.set_brightness(float(value))
            elif kind == "effect.stop":
                await asyncio.to_thread(engine.stop)
            else:
                raise LookupError(f"unknown command {kind!r}")
        except (KeyError, LookupError, ValueError) as e:  # ParamError is a ValueError
            message = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
            with contextlib.suppress(ConnectionClosed):
                await ws.send(json.dumps({"type": "effect.error", "error": message}))

    def _engine_state(self) -> dict:
        return {"type": "engine", "output": self.output_label, **self.engine.state()}

    def _engine_changed(self) -> None:
        """Called from the engine thread: broadcast the new state from the event loop."""
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                lambda: self._broadcast_json(self._engine_state())
            )

    async def _generate(self, ws: ServerConnection, msg: dict) -> None:
        reply: dict = {"type": "generated", "id": msg.get("id")}
        try:
            spec = TreeSpec.from_dict(msg.get("spec"))
            async with self._generate_lock:
                tree = await asyncio.to_thread(generate_tree, spec)
                await asyncio.to_thread(tree.save, self.tree_path)
        except SpecError as e:
            reply.update(ok=False, error=str(e))
        except Exception as e:  # noqa: BLE001 - report anything else to the page too
            log.exception("tree generation failed")
            reply.update(ok=False, error=f"generation failed: {e}")
        else:
            log.info("generated tree seed %d with %d LEDs", tree.seed, tree.led_count)
            reply.update(ok=True, seed=tree.seed, led_count=tree.led_count, warnings=tree.warnings)
        with contextlib.suppress(ConnectionClosed):  # page closed while generating
            await ws.send(json.dumps(reply))

    async def _producer(self, ws: ServerConnection) -> None:
        self.producers += 1
        self._broadcast_json({"type": "status", "producers": self.producers})
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    self.last_frame = message
                    broadcast(self.viewers, message)
        finally:
            self.producers -= 1
            self._broadcast_json({"type": "status", "producers": self.producers})

    def _broadcast_json(self, msg: dict) -> None:
        broadcast(self.viewers, json.dumps(msg))

    async def _watch_files(self) -> None:
        """Tell viewers to reload when the tree or map file is (re)written."""
        seen = {p: _mtime(p) for p in (self.tree_path, self.map_path)}
        while True:
            await asyncio.sleep(self.poll_s)
            for p, old in seen.items():
                new = _mtime(p)
                if new != old:
                    seen[p] = new
                    what = "tree" if p == self.tree_path else "map"
                    log.info("%s file changed, reloading viewers", what)
                    self._broadcast_json({"type": "reload", "what": what})

    # -- lifecycle ----------------------------------------------------------------------

    async def serve(
        self,
        stop: asyncio.Future | None = None,
        on_ready: Callable[[SimServer], None] | None = None,
    ) -> None:
        async with serve(
            self.handler,
            self.host,
            self.port,
            process_request=self.process_request,
            compression=None,
            max_size=2**22,
        ) as server:
            self.port = server.sockets[0].getsockname()[1]  # resolves port 0
            self._loop = asyncio.get_running_loop()
            if self.make_engine is not None:
                self.engine = self.make_engine(self)
                self.engine.on_change = self._engine_changed
            watcher = asyncio.create_task(self._watch_files())
            if on_ready:
                on_ready(self)
            try:
                await (stop if stop is not None else asyncio.Future())
            finally:
                watcher.cancel()
                if self.engine is not None:  # turns the LEDs off while we can still relay
                    await asyncio.to_thread(self.engine.stop)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"


class ServerThread:
    """Runs a :class:`SimServer` on a background event loop (for tests and embedding)."""

    def __init__(self, server: SimServer) -> None:
        self.server = server
        self._loop = asyncio.new_event_loop()
        self._stop: asyncio.Future | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="sim-server", daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._stop = self._loop.create_future()
        try:
            self._loop.run_until_complete(
                self.server.serve(self._stop, on_ready=lambda _: self._ready.set())
            )
        except BaseException as e:  # noqa: BLE001 - surfaced in start()
            self._error = e
            self._ready.set()
        finally:
            self._loop.close()

    def start(self, timeout: float = 5.0) -> ServerThread:
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError("sim server did not start")
        if self._error:
            raise self._error
        return self

    def stop(self) -> None:
        if self._stop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                lambda: self._stop.done() or self._stop.set_result(None)
            )
        self._thread.join(timeout=5)

    def __enter__(self) -> ServerThread:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None


def _response(status: HTTPStatus, body: bytes, content_type: str) -> Response:
    headers = Headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(body))
    headers["Cache-Control"] = "no-store"
    headers["Connection"] = "close"
    return Response(status.value, status.phrase, headers, body)


def _file_response(path: Path, missing_msg: str) -> Response:
    try:
        body = path.read_bytes()
    except FileNotFoundError:
        return _response(
            HTTPStatus.NOT_FOUND,
            json.dumps({"error": missing_msg}).encode(),
            "application/json",
        )
    return _response(HTTPStatus.OK, body, "application/json")
