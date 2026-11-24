"""One device's endpoints, under ``/api/v2/devices/{id}`` (see :mod:`treemap.api.app`).

======  ================  ==============================================================
GET     (the device)      its name, address, whether it answers, its LEDs, map, what's
                          using the LEDs, engine timing, frames received from the phone
POST    /leds             a test pattern (see :mod:`treemap.api.leds`)
GET     /frame            what its LEDs show now: ``seq`` (frames so far) and ``rgb``,
                          base64 of 3 bytes per LED, as sent (after the gamma ``gamma``)
POST    /send             ``{"on"}``: send frames to the controller, or (false) only show
                          them on the server's page, to preview an effect
GET     /play             what's playing: ``effect``, ``params``, ``brightness``, the
                          ``favourite`` last started, the ``playlist`` (``id``, ``name``,
                          ``item``: which of its items, ``next_s``: until the next one)
POST    /play             ``{"effect", "params"}``, ``{"favourite": id}`` or
                          ``{"playlist": id}``: play it, crossfading from what's playing
POST    /play/params      ``{"params"}``: change the playing effect's parameters
POST    /play/next        move the playlist on to its next favourite
POST    /brightness       ``{"brightness": 0-1}``, for every effect
POST    /stop             stop the effect, playlist or test pattern; the LEDs go off
POST    /scan/start       ``{"shape", "symbol_ms", "brightness", "rounds", "camera",
                          "add"}``, all optional; ``camera`` names the phone, see below;
                          ``add`` keeps the rounds so far, to scan parts again
POST    /scan/stop        stop the scan; finished rounds are kept
GET     /scan/state       phase, round, time left, LEDs identified, per-status counts;
                          after a round (and once the scan is done or stopped, if it
                          made a map), ``led_status``: one letter per LED (o ok,
                          i interpolated, f failed); once measured, ``colours``
POST    /scan/frames      a batch of camera frames (see :mod:`treemap.cameras.http`)
POST    /scan/exposure-probe
                          ``{"since", "frames"}``: how many LEDs the frames taken at
                          ``since`` or later (the phone's clock) show, median per frame,
                          and ``lit``, the share of the picture as bright as an LED
POST    /scan/camera-ready
                          ``{"message", "settings"}``: the phone has set its exposure
POST    /scan/next        ``{"finish": false}``: the user is in place, start the next
                          round (or, with ``finish``, end the scan here)
GET     /map              the current map: shape, counts, ``orientation``, ``led_status``
                          (letters as above), the LEDs whose readings are ignored, and
                          ``positions`` as they face the room (null where unknown)
POST    /map/orientation  ``{"front_deg"}`` (tree) or ``{"rotate_deg", "mirror"}``
                          (flat): which way the map faces (see
                          :mod:`treemap.mapping.model`); every effect follows it
POST    /map/interpolate  ``{"index", "interpolate": true}``: ignore an LED's readings
                          (it's in the wrong place) and fill it from its neighbours, or
                          (false) use them again; answers once the map is solved again
POST    /map/adopt        use the map and scans from before there were devices
                          (``data/tree_map.json``), if it has as many LEDs
POST    /map/truth        a virtual WLED's true LED positions as the map, in place of a
                          scan (:mod:`treemap.sim.truth`)
======  ================  ==============================================================

A scan started with ``camera`` (the page sends the phone's model and camera label) sets
the phone up first: after the countdown, in phase ``exposure``, the LEDs light up at
the scan's brightness, each in one of the code's colours, while the page tries exposures,
asking ``exposure-probe`` how many LEDs each one shows, and keeps the shortest that shows
nearly all (so the dimmest colour too); it then calls
``camera-ready``. In phase ``colours`` the server measures how the phone sees each colour
of the code and keeps that per phone (``colours`` in the state: the share read right
per colour, whether all pass, tips). Then the rounds start. After each round (but the
last) the LEDs show its result until the page calls ``next`` (``waiting`` in the state),
so the user can walk to the red parts first.

One thing drives the LEDs at a time. A test pattern or an effect (or playlist) replaces
whichever of the two was showing; a scan stops both, and neither can start until the scan
is over.
"""

from __future__ import annotations

import base64
import shutil
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from treemap.api.http import HttpError, Request
from treemap.api.leds import CommandError, LedCommands
from treemap.cameras.http import BatchError, HttpCamera
from treemap.scan.track import MIN_LEVEL, find_blobs
from treemap.workflow import WorkflowError
from treemap.config import Config
from treemap.devices import DeviceOutput, DeviceRecord
from treemap.effects import EffectContext, ParamError
from treemap.engine import Engine
from treemap.jobs import JobRejected, Jobs
from treemap.library import Library
from treemap.mapping.model import MapFile, TreeMap
from treemap.outputs.base import LedOutput
from treemap.player import Player
from treemap.sim.truth import fetch_true_map

CAMERA_ID = "browser"  # whose measured colours a scan from the page reads by
STATUS_LETTERS = {"ok": "o", "interpolated": "i", "failed": "f"}
NEXT_TIMEOUT_S = 900.0  # between rounds, for the user; then the scan finishes there
READY_TIMEOUT_S = 300.0  # for the page to set the phone's exposure (the user may pick one)
PROBE_TIMEOUT_S = 3.0  # for the frames an exposure probe asks for to arrive
SOLVE_TIMEOUT_S = 300.0  # for the map to be solved again after a fix


class SharedOutput(LedOutput):
    """A device's one output, handed to the engine and the scan: they close what
    they're given when they finish, but the real output stays open."""

    def __init__(self, output: LedOutput) -> None:
        super().__init__(output.led_count)
        self.output = output

    def _show(self, colors: np.ndarray) -> None:
        self.output.show(colors)


class DeviceApi:
    """One device: its output, effects engine and player, test patterns and scans.

    ``cfg`` is the server's config with this device's LEDs and data folder filled in
    (see :meth:`treemap.api.app.Api._device_config`)."""

    ROUTES = (
        ("POST", "/leds", "post_leds"),
        ("GET", "/frame", "frame"),
        ("POST", "/send", "set_send"),
        ("GET", "/play", "playing"),
        ("POST", "/play", "play"),
        ("POST", "/play/params", "play_params"),
        ("POST", "/play/next", "play_next"),
        ("POST", "/brightness", "brightness"),
        ("POST", "/stop", "stop"),
        ("POST", "/scan/start", "scan_start"),
        ("POST", "/scan/stop", "scan_stop"),
        ("GET", "/scan/state", "scan_state"),
        ("POST", "/scan/frames", "scan_frames"),
        ("POST", "/scan/exposure-probe", "exposure_probe"),
        ("POST", "/scan/camera-ready", "camera_ready"),
        ("POST", "/scan/next", "scan_next"),
        ("GET", "/map", "get_map"),
        ("POST", "/map/orientation", "map_orientation"),
        ("POST", "/map/interpolate", "map_interpolate"),
        ("POST", "/map/adopt", "map_adopt"),
        ("POST", "/map/truth", "map_truth"),
    )

    def __init__(self, record: DeviceRecord, cfg: Config, output: DeviceOutput,
                 library: Library, legacy_dir: Path | None = None,
                 camera: HttpCamera | None = None) -> None:
        self.record = record
        self.cfg = cfg
        self.output = output
        self.n = output.led_count
        self.legacy_dir = legacy_dir  # data/, where the map was kept before devices
        self.camera = camera or HttpCamera()
        shared = lambda: SharedOutput(output)  # noqa: E731
        fps = cfg.engine.fps
        self.engine = Engine(
            shared, EffectContext(n=self.n, fps=fps, tree_map=MapFile(cfg.map_path),
                                  palettes=library.palette_colors),
            fps=fps, brightness=cfg.engine.brightness, crossfade_s=cfg.engine.crossfade,
            gamma=cfg.gamma,
        )
        self.library = library
        self.player = Player(self.engine, library)
        self.leds = LedCommands(output, self._map_for_leds)
        self._scan_started: datetime | None = None  # when the latest scan started (UTC)
        self._ready = threading.Event()  # the page has set the phone's exposure
        self._ready_info: dict[str, Any] = {}
        self._probing = threading.Lock()
        self._go = threading.Condition()
        self._go_round = 0  # the user has asked for rounds up to this one
        self._finish = False
        self.jobs = Jobs(cfg, shared, stop_effects=self._free_leds, camera=self.camera,
                         camera_id=CAMERA_ID, camera_ready=self._wait_camera_ready,
                         next_round=self._wait_next_round)

    # -- who drives the LEDs ------------------------------------------------------------

    def _free_leds(self) -> None:
        self.leds.stop()
        self.player.stop()

    def _refuse_while_scanning(self) -> None:
        if self.jobs.uses_leds:
            raise HttpError(409, "a scan is using the LEDs; stop it first")

    def _load_map(self) -> TreeMap | None:
        try:
            return TreeMap.load(self.cfg.map_path)
        except (OSError, ValueError, KeyError):
            return None

    def _map_for_leds(self) -> TreeMap:
        tree_map = self._load_map()
        if tree_map is None or tree_map.led_count != self.n:
            raise CommandError("there's no map for these LEDs yet: scan first")
        return tree_map

    def _map_or_404(self) -> TreeMap:
        tree_map = self._load_map()
        if tree_map is None:
            raise HttpError(404, "there's no map yet: scan first")
        if tree_map.led_count != self.n:
            raise HttpError(409, f"the map is for {tree_map.led_count} LEDs, not "
                                 f"{self.n}: scan again")
        return tree_map

    @staticmethod
    def _orientation(tree_map: TreeMap) -> dict[str, Any]:
        """The map's orientation, with the defaults filled in."""
        default = {"rotate_deg": 0.0, "mirror": False} if tree_map.shape == "flat" else {"front_deg": 0.0}
        return {**default, **(tree_map.orientation or {})}

    # -- endpoints ----------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """What the device page and the scan page show about it (``GET /devices/{id}``)."""
        cfg = self.cfg
        tree_map = self._load_map()
        busy = ("scan" if self.jobs.uses_leds else "effect" if self.engine.running
                else "leds" if self.leds.running else None)
        last = self.camera.last_push
        return {
            "shape": cfg.shape,
            "led_count": self.n,
            "map": None if tree_map is None else {
                "led_count": tree_map.led_count,
                "fits": tree_map.led_count == self.n,
                "shape": tree_map.shape,
                "created": tree_map.meta.get("created"),
                "source": tree_map.meta.get("source"),  # "virtual WLED": its true positions
                "counts": tree_map.counts(),
                "orientation": self._orientation(tree_map),
            },
            "legacy_map": self._legacy_map() is not None and tree_map is None,
            "busy": busy,
            "leds": self.leds.mode,
            "effect": self.engine.state()["running"],
            "send": self.output.send,
            "gamma": cfg.gamma,
            "timing": self.engine.timing(),
            "camera": {"frames": self.camera.received,
                       "last_s_ago": round(time.monotonic() - last, 1) if last else None},
        }

    def post_leds(self, req: Request) -> dict[str, Any]:
        self._refuse_while_scanning()
        try:
            return self.leds.run(req.json(), before=self.player.stop)
        except CommandError as e:
            raise HttpError(400, str(e)) from None

    # -- effects ------------------------------------------------------------------------

    def frame(self, req: Request) -> dict[str, Any]:
        out = self.output
        return {"seq": out.seq, "rgb": base64.b64encode(out.frame.tobytes()).decode()}

    def set_send(self, req: Request) -> dict[str, Any]:
        on = req.json().get("on")
        if not isinstance(on, bool):
            raise HttpError(400, "on must be true or false")
        self.output.set_send(on)
        return {"send": on}

    def playing(self, req: Request) -> dict[str, Any]:
        return self.player.state()

    def play(self, req: Request) -> dict[str, Any]:
        self._refuse_while_scanning()
        body = req.json()
        params = body.get("params") or {}
        kinds = [k for k in ("effect", "favourite", "playlist") if k in body]
        if len(kinds) != 1 or not isinstance(body[kinds[0]], str) or not isinstance(params, dict):
            raise HttpError(400, 'send {"effect": name, "params": {...}}, {"favourite": id} '
                                 'or {"playlist": id}')
        self.leds.stop()
        try:
            if "effect" in body:
                self.player.play_effect(body["effect"], params)
            elif "favourite" in body:
                self.player.play_favourite(body["favourite"])
            else:
                self.player.play_playlist(body["playlist"])
        except KeyError as e:
            raise HttpError(404, e.args[0] if e.args else "no such effect") from None
        except ParamError as e:
            raise HttpError(400, str(e)) from None
        self.leds.mode = None
        return self.player.state()

    def play_params(self, req: Request) -> dict[str, Any]:
        self._refuse_while_scanning()
        params = req.json().get("params")
        if not isinstance(params, dict):
            raise HttpError(400, 'send {"params": {...}}')
        try:
            self.player.set_params(params)
        except LookupError as e:
            raise HttpError(409, str(e)) from None
        except ParamError as e:
            raise HttpError(400, str(e)) from None
        return self.player.state()

    def play_next(self, req: Request) -> dict[str, Any]:
        try:
            self.player.skip()
        except LookupError as e:
            raise HttpError(409, str(e)) from None
        return self.player.state()

    def brightness(self, req: Request) -> dict[str, Any]:
        value = req.json().get("brightness")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise HttpError(400, "brightness must be a number 0-1")
        self.engine.set_brightness(float(value))
        return self.player.state()

    def stop(self, req: Request) -> dict[str, Any]:
        if not self.jobs.uses_leds:
            self._free_leds()
            self.output.off()  # a still test pattern stays up otherwise
            self.leds.mode = None
        return self.player.state()

    def scan_start(self, req: Request) -> tuple[int, dict[str, Any]]:
        body = req.json()
        unknown = set(body) - {"shape", "symbol_ms", "brightness", "rounds", "camera", "add"}
        if unknown:
            raise HttpError(400, f"unknown setting(s): {', '.join(sorted(unknown))}")
        if self.jobs.busy:
            raise HttpError(409, f"a {self.jobs.state()['kind']} is already running")
        started = datetime.now(timezone.utc)
        self._ready.clear()
        with self._go:
            self._go_round, self._finish = 0, False
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
            "waiting": bool(progress.get("waiting")) and st["status"] == "running",
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

    # -- the map ----------------------------------------------------------------------

    def get_map(self, req: Request) -> dict[str, Any]:
        m = self._map_or_404()
        return {
            "shape": m.shape,
            "led_count": m.led_count,
            "created": m.meta.get("created"),
            "rounds": m.meta.get("rounds"),
            "counts": m.counts(),
            "orientation": self._orientation(m),
            "led_status": "".join(STATUS_LETTERS.get(str(s), "f") for s in m.status),
            "ignored": sorted(m.meta.get("forced_interpolate", [])),
            "positions": [None if not ok else [round(float(c), 4) for c in p]
                          for p, ok in zip(m.geometry.xyz, m.geometry.valid)],
        }

    def _legacy_map(self) -> TreeMap | None:
        """The map from before there were devices, if it fits these LEDs."""
        if self.legacy_dir is None:
            return None
        try:
            m = TreeMap.load(self.legacy_dir / "tree_map.json")
        except (OSError, ValueError, KeyError):
            return None
        return m if m.led_count == self.n else None

    def map_adopt(self, req: Request) -> dict[str, Any]:
        if self.jobs.busy:
            raise HttpError(409, f"a {self.jobs.state()['kind']} is changing the map; wait for it")
        if self._load_map() is not None:
            raise HttpError(409, "this device has a map already")
        if self._legacy_map() is None:
            raise HttpError(404, f"there's no map with {self.n} LEDs from before devices")
        self.cfg.map_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.legacy_dir / "tree_map.json", self.cfg.map_path)
        scans = self.legacy_dir / "scans" / self.cfg.scan.profile
        if scans.is_dir() and not self.cfg.scan_dir.exists():
            shutil.copytree(scans, self.cfg.scan_dir)  # so it can be solved again
        return self.get_map(req)

    def map_truth(self, req: Request) -> dict[str, Any]:
        """The virtual WLED's true LED positions as the map, in place of a scan."""
        if not self.record.virtual:
            raise HttpError(400, "only the virtual WLED knows where its LEDs really are")
        if self.jobs.busy:
            raise HttpError(409, f"a {self.jobs.state()['kind']} is changing the map; wait for it")
        try:
            tree_map = fetch_true_map(self.record.host)
        except OSError as e:
            raise HttpError(502, f"can't reach the virtual WLED: {e}") from None
        except (ValueError, KeyError, TypeError) as e:
            raise HttpError(502, f"the virtual WLED's layout can't be read: {e}") from None
        if tree_map.led_count != self.n:
            raise HttpError(409, f"the virtual WLED has {tree_map.led_count} LEDs now, "
                                 f"this device {self.n}")
        tree_map.save(self.cfg.map_path)
        return self.get_map(req)

    def map_orientation(self, req: Request) -> dict[str, Any]:
        if self.jobs.busy:
            raise HttpError(409, f"a {self.jobs.state()['kind']} is changing the map; wait for it")
        try:
            self._map_or_404().turned(req.json()).save(self.cfg.map_path)
        except ValueError as e:
            raise HttpError(400, str(e)) from None
        return self.get_map(req)

    def map_interpolate(self, req: Request) -> dict[str, Any]:
        body = req.json()
        interpolate = body.get("interpolate", True)
        if not isinstance(interpolate, bool):
            raise HttpError(400, "interpolate must be true or false")
        self._map_or_404()
        try:
            self.jobs.start("interpolate" if interpolate else "measure", {"index": body.get("index")})
        except JobRejected as e:
            raise HttpError(409 if self.jobs.busy else 400, str(e)) from None
        if not self.jobs.wait(SOLVE_TIMEOUT_S):
            raise HttpError(504, "solving the map is taking too long; check it later")
        st = self.jobs.state()
        if st["status"] != "done":
            raise HttpError(500, st.get("error") or "the map couldn't be solved again")
        return self.get_map(req)

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
            lit = [float(np.mean(f.image.max(axis=2) >= MIN_LEVEL)) for f in frames]
        finally:
            self._probing.release()
        return {"frames": len(frames), "leds": int(np.median(counts)) if counts else 0,
                "lit": round(float(np.median(lit)), 4) if lit else 0.0}

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

    def scan_next(self, req: Request) -> dict[str, Any]:
        finish = req.json().get("finish", False)
        if not isinstance(finish, bool):
            raise HttpError(400, "finish must be true or false")
        progress = self.jobs.state().get("progress") or {}
        if not (self.jobs.uses_leds and progress.get("waiting")):
            raise HttpError(409, "the scan isn't waiting between rounds")
        with self._go:
            self._go_round = max(self._go_round, int(progress.get("round") or 0) + 1)
            self._finish = finish
            self._go.notify_all()
        return {"round": self._go_round, "finish": finish}

    def _wait_next_round(self, round_: int, check_cancel: Callable[[], None]) -> bool:
        end = time.monotonic() + NEXT_TIMEOUT_S
        with self._go:
            while self._go_round < round_ + 1:
                self._go.wait(0.25)
                check_cancel()
                if time.monotonic() > end:
                    return False  # nobody came back: keep what's done
            return not self._finish

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
