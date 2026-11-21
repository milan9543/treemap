"""Background jobs for the viewer: scan, reconstruct, fix and evaluate.

One job runs at a time on its own thread; its state (progress, the result or error) is
reported through ``on_change`` so the server can broadcast it. The scan lights the LEDs,
so it first stops the effects engine via ``stop_effects``.

Job kinds and their parameters:

* ``scan``: ``rounds`` (int, default scan.max_rounds); ``shape`` (tree or flat),
  ``symbol_ms`` and ``brightness`` override the config for this scan; ``camera`` (the
  scan page's phone) makes it wait for the page to set the exposure, then measure that
  phone's colours. Starts over
  (earlier rounds are forgotten) and runs until every LED is ok, the rounds are done, or
  it's stopped.
* ``reconstruct``: solve again from the saved rounds
* ``evaluate`` (simulator only)
* ``interpolate``, ``measure``: ``index``; interpolate ignores that LED's observations
  from now on, measure uses them again. Each rebuilds the map afterwards.
"""

from __future__ import annotations

import copy
import dataclasses
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from treemap import workflow
from treemap.cameras.base import Camera
from treemap.config import SHAPES, Config
from treemap.outputs.base import LedOutput

log = logging.getLogger(__name__)

KINDS = ("scan", "reconstruct", "evaluate", "interpolate", "measure")
USES_LEDS = ("scan",)


class JobRejected(ValueError):
    """A job can't start: another is running, or its parameters are invalid."""


class JobCancelled(Exception):
    pass


class Jobs:
    def __init__(
        self,
        cfg: Config,
        output_factory: Callable[[], LedOutput],
        stop_effects: Callable[[], None] = lambda: None,
        on_change: Callable[[dict], None] | None = None,
        progress_interval: float = 0.1,
        sim_port: int | None = None,
        camera: Camera | None = None,
        camera_id: str | None = None,
        camera_ready: workflow.CameraReady | None = None,
    ) -> None:
        self.cfg = cfg
        self.sim_port = sim_port  # where the viewer's camera frames come from
        # The camera scans use instead of the configured one (the phone's page, for
        # `treemap serve`), and the name its measured colours are kept under. A scan
        # that names its phone (`camera`) waits on `camera_ready` for the page to set
        # the exposure, then measures that phone's colours.
        self.camera, self.camera_id, self.camera_ready = camera, camera_id, camera_ready
        self.output_factory = output_factory
        self.stop_effects = stop_effects
        self.on_change = on_change
        self.progress_interval = progress_interval
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {"id": 0, "kind": None, "status": "idle"}
        self._last_emit = 0.0

    # -- control (any thread) ---------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def uses_leds(self) -> bool:
        return self.busy and self._state.get("kind") in USES_LEDS

    def state(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    def start(self, kind: str, params: dict[str, Any] | None = None) -> int:
        """Start a job; raises :class:`JobRejected`."""
        if kind not in KINDS:
            raise JobRejected(f"unknown job {kind!r}; one of {', '.join(KINDS)}")
        params = params or {}
        if not isinstance(params, dict):
            raise JobRejected("params must be an object")
        try:
            run = getattr(self, f"_prepare_{kind}")(params)
        except workflow.WorkflowError as e:
            raise JobRejected(str(e)) from None
        with self._lock:
            if self.busy:
                raise JobRejected(f"a {self._state['kind']} is already running")
            self._cancel.clear()
            self._state = {
                "id": self._state["id"] + 1, "kind": kind, "params": params,
                "status": "running", "message": "", "progress": None,
                "result": None, "error": None,
            }
            self._thread = threading.Thread(target=self._run, args=(run,), name=f"job-{kind}",
                                            daemon=True)
            self._thread.start()
            job_id = self._state["id"]
        self._emit(force=True)
        return job_id

    def cancel(self) -> None:
        if self.busy:
            self._cancel.set()
            self._update(message="stopping…")

    def wait(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return not self.busy

    # -- job thread ---------------------------------------------------------------------

    def _run(self, run: Callable[[], dict | None]) -> None:
        try:
            result = run()
        except JobCancelled:
            self._update(status="cancelled", message="stopped; finished rounds were saved")
        except workflow.WorkflowError as e:
            self._update(status="error", error=str(e))
        except Exception as e:  # noqa: BLE001 - shown in the viewer
            log.exception("job failed")
            self._update(status="error", error=f"{type(e).__name__}: {e}")
        else:
            self._update(status="done", result=result, message="")

    def _update(self, **changes: Any) -> None:
        with self._lock:
            self._state.update(changes)
        self._emit(force=True)

    def _emit(self, force: bool = False) -> None:
        now = time.monotonic()
        if self.on_change is None or (not force and now - self._last_emit < self.progress_interval):
            return
        self._last_emit = now
        try:
            self.on_change(self.state())
        except Exception:  # noqa: BLE001
            log.exception("job on_change callback failed")

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled

    def _on_update(self, update: dict) -> None:
        with self._lock:
            self._state["progress"] = update
            if "colours" in update:  # kept for the rest of the scan
                self._state["colours"] = update["colours"]
        self._emit(force=update.get("phase") != "flashing")

    def _with_output(self, body: Callable[[LedOutput], Any]) -> Any:
        """Stop the effects, open the LED output for ``body``, and turn it off after."""
        self._update(message="stopping effects…")
        self.stop_effects()
        out = self.output_factory()
        try:
            self._update(message="")
            return body(out)
        finally:
            try:
                out.off()
            finally:
                out.close()

    # -- the jobs: _prepare_* validates parameters, then returns the work ---------------

    def _prepare_scan(self, p: dict) -> Callable[[], dict]:
        rounds = p.get("rounds")
        if rounds is not None and not _whole(rounds, 1):
            raise workflow.WorkflowError("rounds must be a whole number >= 1")
        cfg = copy.copy(self.cfg)  # shallow: keeps the controllers already read from WLED
        if p.get("shape") is not None:
            if p["shape"] not in SHAPES:
                raise workflow.WorkflowError(f"shape must be one of {', '.join(SHAPES)}")
            cfg.shape = p["shape"]
        limits = {"symbol_ms": (40, 2000), "brightness": (1, 255)}
        changes = {}
        for key, (lo, hi) in limits.items():
            if p.get(key) is not None:
                if not _whole(p[key], lo, hi):
                    raise workflow.WorkflowError(f"{key} must be a whole number {lo}-{hi}")
                changes[key] = p[key]
        cfg.scan = dataclasses.replace(cfg.scan, **changes)
        camera_id, camera_ready = self.camera_id, None
        if p.get("camera") is not None:
            if self.camera_ready is None:
                raise workflow.WorkflowError("this server's scans can't take a camera")
            if not isinstance(p["camera"], str) or not 0 < len(p["camera"].strip()) <= 200:
                raise workflow.WorkflowError("camera must be the phone's camera name")
            camera_id, camera_ready = p["camera"].strip(), self.camera_ready

        def run() -> dict:
            workflow.ensure_sim_tree(cfg)
            tree_map = self._with_output(lambda out: workflow.run_scan(
                cfg, out, rounds=rounds, sim_port=self.sim_port, camera=self.camera,
                camera_id=camera_id, camera_ready=camera_ready,
                on_update=self._on_update, check_cancel=self._check_cancel,
                on_message=lambda m: self._update(message=m),
            ))
            return workflow.map_summary(tree_map) if tree_map is not None else {}

        return run

    def _prepare_reconstruct(self, p: dict) -> Callable[[], dict]:
        def run() -> dict:
            return workflow.map_summary(workflow.rebuild_map(self.cfg)[0])

        return run

    def _prepare_evaluate(self, p: dict) -> Callable[[], dict]:
        def run() -> dict:
            return workflow.evaluation_summary(workflow.evaluate_sim(self.cfg))

        return run

    def _index(self, p: dict) -> int:
        i = p.get("index")
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < self.cfg.led_count:
            raise workflow.WorkflowError(f"index must be an LED number 0-{self.cfg.led_count - 1}")
        return i

    def _prepare_interpolate(self, p: dict) -> Callable[[], dict]:
        return self._override(self._index(p), True)

    def _prepare_measure(self, p: dict) -> Callable[[], dict]:
        return self._override(self._index(p), False)

    def _override(self, index: int, interpolate: bool) -> Callable[[], dict]:
        def run() -> dict:
            workflow.set_interpolate(self.cfg, index, interpolate)
            return self._rebuilt(index)

        return run

    def _rebuilt(self, index: int) -> dict:
        tree_map, _ = workflow.rebuild_map(self.cfg)
        return {"index": index, "status": str(tree_map.status[index]),
                **workflow.map_summary(tree_map)}


def _whole(v: Any, lo: int, hi: int | None = None) -> bool:
    return (not isinstance(v, bool) and isinstance(v, int) and v >= lo
            and (hi is None or v <= hi))
