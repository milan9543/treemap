"""The ``/api/v1`` endpoints of ``treemap serve``.

======  ================  ==============================================================
GET     /info             API and server version, the LEDs and controllers, the current
                          map, what's using the LEDs, engine timing, frames received
POST    /leds             a test pattern (see :mod:`treemap.api.leds`)
POST    /play             ``{"effect", "params"}``: run an effect
POST    /scan/start       ``{"shape", "symbol_ms", "brightness", "rounds", "camera"}``,
                          all optional; ``camera`` names the phone, see below
POST    /scan/stop        stop the scan; finished rounds are kept
GET     /scan/state       phase, round, time left, LEDs identified, per-status counts;
                          after a round (and once the scan is done or stopped, if it
                          made a map), ``led_status``: one letter per LED (o ok,
                          i interpolated, f failed); once measured, ``colours``
POST    /scan/frames      a batch of camera frames (see :mod:`treemap.cameras.http`)
POST    /scan/exposure-probe
                          ``{"since", "frames"}``: how many LEDs the frames taken at
                          ``since`` or later (the phone's clock) show, median per frame
POST    /scan/camera-ready
                          ``{"message", "settings"}``: the phone has set its exposure
======  ================  ==============================================================

A scan started with ``camera`` (the page sends the phone's model and camera label) sets
the phone up first: after the countdown, in phase ``exposure``, the LEDs show white at
the scan's brightness while the page tries exposures, asking ``exposure-probe`` how many
LEDs each one shows, and keeps the shortest that shows nearly all; it then calls
``camera-ready``. In phase ``colours`` the server measures how the phone sees each colour
of the code and keeps that per phone (``colours`` in the state: the share read right
per colour, whether all pass, tips). Then the rounds start.

One thing drives the LEDs at a time. A test pattern or an effect replaces whichever of
the two was showing; a scan stops both, and neither can start until the scan is over.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import numpy as np

from treemap import __version__
from treemap.api.http import HttpError, Request, Router
from treemap.api.leds import CommandError, LedCommands
from treemap.cameras.http import BatchError, HttpCamera
from treemap.scan.track import find_blobs
from treemap.workflow import WorkflowError
from treemap.config import Config
from treemap.effects import EffectContext, ParamError
from treemap.engine import Engine
from treemap.jobs import JobRejected, Jobs
from treemap.mapping.model import TreeMap
from treemap.mapping.quality import status_frame
from treemap.mapping.source import MapSource
from treemap.outputs.base import LedOutput

API_VERSION = 1
PREFIX = "/api/v1"
CAMERA_ID = "browser"  # whose measured colours a scan from the page reads by
STATUS_LETTERS = {"ok": "o", "interpolated": "i", "failed": "f"}
READY_TIMEOUT_S = 90.0  # for the page to set the phone's exposure
PROBE_TIMEOUT_S = 3.0  # for the frames an exposure probe asks for to arrive


class SharedOutput(LedOutput):
    """The server's one output, handed to the engine and the scan: they close what
    they're given when they finish, but the real output stays open."""

    def __init__(self, output: LedOutput) -> None:
        super().__init__(output.led_count)
        self.output = output

    def _show(self, colors: np.ndarray) -> None:
        self.output.show(colors)


class Api:
    def __init__(self, cfg: Config, output: LedOutput, camera: HttpCamera | None = None) -> None:
        self.cfg = cfg
        self.output = output
        self.n = output.led_count
        self.camera = camera or HttpCamera()
        shared = lambda: SharedOutput(output)  # noqa: E731
        fps = cfg.engine.fps
        self.engine = Engine(
            shared, EffectContext(n=self.n, fps=fps, tree_map=MapSource(cfg.map_path)),
            fps=fps, brightness=cfg.engine.brightness, crossfade_s=cfg.engine.crossfade,
            gamma=cfg.gamma,
        )
        self.leds = LedCommands(output, self._status_frame)
        self._scan_started: datetime | None = None  # when the latest scan started (UTC)
        self._ready = threading.Event()  # the page has set the phone's exposure
        self._ready_info: dict[str, Any] = {}
        self._probing = threading.Lock()
        self.jobs = Jobs(cfg, shared, stop_effects=self._free_leds, camera=self.camera,
                         camera_id=CAMERA_ID, camera_ready=self._wait_camera_ready)
        self.router = Router()
        for method, path, handler in (
            ("GET", "/info", self.info),
            ("POST", "/leds", self.post_leds),
            ("POST", "/play", self.play),
            ("POST", "/scan/start", self.scan_start),
            ("POST", "/scan/stop", self.scan_stop),
            ("GET", "/scan/state", self.scan_state),
            ("POST", "/scan/frames", self.scan_frames),
            ("POST", "/scan/exposure-probe", self.exposure_probe),
            ("POST", "/scan/camera-ready", self.camera_ready),
        ):
            self.router.add(method, PREFIX + path, handler)

    # -- who drives the LEDs ------------------------------------------------------------

    def _free_leds(self) -> None:
        self.leds.stop()
        self.engine.stop()

    def _refuse_while_scanning(self) -> None:
        if self.jobs.uses_leds:
            raise HttpError(409, "a scan is using the LEDs; stop it first")

    def _load_map(self) -> TreeMap | None:
        try:
            return TreeMap.load(self.cfg.map_path)
        except (OSError, ValueError, KeyError):
            return None

    def _status_frame(self) -> np.ndarray:
        tree_map = self._load_map()
        if tree_map is None or tree_map.led_count != self.n:
            raise CommandError("there's no map for these LEDs yet: scan first")
        return status_frame(tree_map)

    # -- endpoints ----------------------------------------------------------------------

    def info(self, req: Request) -> dict[str, Any]:
        cfg = self.cfg
        tree_map = self._load_map()
        busy = ("scan" if self.jobs.uses_leds else "effect" if self.engine.running
                else "leds" if self.leds.running else None)
        last = self.camera.last_push
        return {
            "api": API_VERSION,
            "server": f"treemap {__version__}",
            "shape": cfg.shape,
            "output": cfg.output,
            "led_count": self.n,
            "controllers": [asdict(c) for c in cfg.controller_layout()]
            if cfg.output == "wled" else [],
            "map": None if tree_map is None else {
                "led_count": tree_map.led_count,
                "fits": tree_map.led_count == self.n,
                "shape": tree_map.meta.get("shape", "tree"),
                "created": tree_map.meta.get("created"),
                "counts": tree_map.counts(),
            },
            "busy": busy,
            "leds": self.leds.mode,
            "effect": self.engine.state()["running"],
            "timing": self.engine.timing(),
            "camera": {"frames": self.camera.received,
                       "last_s_ago": round(time.monotonic() - last, 1) if last else None},
        }

    def post_leds(self, req: Request) -> dict[str, Any]:
        self._refuse_while_scanning()
        try:
            return self.leds.run(req.json(), before=self.engine.stop)
        except CommandError as e:
            raise HttpError(400, str(e)) from None

    def play(self, req: Request) -> dict[str, Any]:
        self._refuse_while_scanning()
        body = req.json()
        params = body.get("params") or {}
        if not isinstance(body.get("effect"), str) or not isinstance(params, dict):
            raise HttpError(400, 'send {"effect": name, "params": {...}}')
        self.leds.stop()
        try:
            self.engine.start(body["effect"], params)
        except KeyError as e:
            raise HttpError(404, e.args[0] if e.args else "no such effect") from None
        except ParamError as e:
            raise HttpError(400, str(e)) from None
        self.leds.mode = None
        return self.engine.state()

    def scan_start(self, req: Request) -> tuple[int, dict[str, Any]]:
        body = req.json()
        unknown = set(body) - {"shape", "symbol_ms", "brightness", "rounds", "camera"}
        if unknown:
            raise HttpError(400, f"unknown setting(s): {', '.join(sorted(unknown))}")
        if self.jobs.busy:
            raise HttpError(409, f"a {self.jobs.state()['kind']} is already running")
        started = datetime.now(timezone.utc)
        self._ready.clear()
        try:
            job = self.jobs.start("scan", body)
        except JobRejected as e:
            raise HttpError(400, str(e)) from None
        self._scan_started = started
        self.leds.mode = None
        return 202, {"id": job}

    def scan_stop(self, req: Request) -> dict[str, Any]:
        self.jobs.cancel()
        return {"stopping": self.jobs.busy}

    def scan_state(self, req: Request) -> dict[str, Any]:
        st = self.jobs.state()
        progress = st.get("progress") or {}
        out = {
            "id": st["id"],
            "status": st["status"] if st.get("kind") in (None, "scan") else "idle",
            "message": st.get("message") or "",
            "error": st.get("error"),
            **{k: progress.get(k) for k in ("phase", "round", "remaining", "frames",
                                            "identified", "counts")},
            "frames_received": self.camera.received,
            "colours": st.get("colours"),
        }
        if progress.get("message"):
            out["message"] = progress["message"]
        if progress.get("phase") == "status" or st["status"] in ("done", "cancelled"):
            tree_map = self._load_map()
            if tree_map is not None and tree_map.led_count == self.n and self._made_by_scan(tree_map):
                out["led_status"] = "".join(STATUS_LETTERS.get(str(s), "f") for s in tree_map.status)
                out["counts"] = tree_map.counts()
        return out

    def _made_by_scan(self, tree_map: TreeMap) -> bool:
        """Whether the map came from the latest scan (not one from before it, which a scan
        that found nothing leaves in place)."""
        if self._scan_started is None:
            return False
        try:
            created = datetime.fromisoformat(tree_map.meta["created"])
            # `created` is to the second, and a scan takes seconds before its first map
            return created > self._scan_started.replace(microsecond=0)
        except (KeyError, TypeError, ValueError):
            return False

    def scan_frames(self, req: Request) -> dict[str, Any]:
        if req.content_type != "application/octet-stream":
            raise HttpError(415, "send frames as application/octet-stream")
        try:
            return {"frames": self.camera.push(req.body)}
        except BatchError as e:
            raise HttpError(400, str(e)) from None

    # -- setting the phone up ---------------------------------------------------------

    def _waiting_for_camera(self) -> bool:
        return self.jobs.uses_leds and (self.jobs.state().get("progress") or {}).get(
            "phase") == "exposure"

    def exposure_probe(self, req: Request) -> dict[str, Any]:
        body = req.json()
        since, count = body.get("since"), body.get("frames", 6)
        if isinstance(since, bool) or not isinstance(since, (int, float)):
            raise HttpError(400, "since must be a time in seconds on the phone's clock")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 24:
            raise HttpError(400, "frames must be a whole number 1-24")
        if self.jobs.uses_leds and not self._waiting_for_camera():
            raise HttpError(409, "the scan is reading the camera")
        if not self._probing.acquire(blocking=False):
            raise HttpError(409, "another probe is running")
        try:
            frames = self.camera.frames_since(float(since), count, PROBE_TIMEOUT_S)
            counts = [len(find_blobs(f.image)) for f in frames]
        finally:
            self._probing.release()
        return {"frames": len(frames), "leds": int(np.median(counts)) if counts else 0}

    def camera_ready(self, req: Request) -> dict[str, Any]:
        body = req.json()
        message, settings = body.get("message"), body.get("settings") or {}
        if message is not None and (not isinstance(message, str) or len(message) > 1000):
            raise HttpError(400, "message must be text")
        if not isinstance(settings, dict):
            raise HttpError(400, "settings must be an object")
        if not self._waiting_for_camera():
            raise HttpError(409, "no scan is waiting for the camera")
        self._ready_info = {"message": message, "settings": settings}
        self._ready.set()
        return {"ok": True}

    def _wait_camera_ready(self, check_cancel: Callable[[], None]) -> dict[str, Any]:
        end = time.monotonic() + READY_TIMEOUT_S
        while not self._ready.wait(0.25):
            check_cancel()
            if time.monotonic() > end:
                raise WorkflowError("the phone didn't set its exposure: is the scan page "
                                    "still open?")
        return self._ready_info

    # -- lifecycle ----------------------------------------------------------------------

    def close(self) -> None:
        """Stop the scan (keeping finished rounds), the effect and the test pattern, turn
        the LEDs off and close the output."""
        if self.jobs.busy:
            self.jobs.cancel()
            self.jobs.wait(10)
        self._free_leds()
        try:
            self.output.off()
        finally:
            self.output.close()


def lan_address() -> str:
    """This machine's address on the LAN (the interface with the default route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # sends nothing; just picks the interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
