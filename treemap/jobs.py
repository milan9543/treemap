"""Background jobs for the viewer: scan, reconstruct, fix and evaluate.

One job runs at a time on its own thread; its state (progress, a question for the user,
the result or error) is reported through ``on_change`` so the server can broadcast it.
Jobs that light LEDs (scan, rescan) first stop the effects engine via ``stop_effects``.

Job kinds and their parameters:

* ``scan``: ``angles`` (list, default scan.angles), ``leds`` ("120-140", default all not
  yet scanned), ``fresh`` (bool), ``flash`` (seconds)
* ``reconstruct``
* ``evaluate`` (simulator only)
* ``rescan``, ``interpolate``, ``measure``: ``index``; rescan photographs one LED again,
  interpolate ignores its detections from now on, measure uses them again. Each
  rebuilds the map afterwards.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from treemap import workflow
from treemap.config import Config
from treemap.outputs.base import LedOutput

log = logging.getLogger(__name__)

KINDS = ("scan", "reconstruct", "evaluate", "rescan", "interpolate", "measure")
USES_LEDS = ("scan", "rescan")


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
    ) -> None:
        self.cfg = cfg
        self.output_factory = output_factory
        self.stop_effects = stop_effects
        self.on_change = on_change
        self.progress_interval = progress_interval
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._proceed = threading.Event()
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
            self._proceed.clear()
            self._state = {
                "id": self._state["id"] + 1, "kind": kind, "params": params,
                "status": "running", "message": "", "progress": None, "prompt": None,
                "angles": [], "result": None, "error": None,
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

    def proceed(self) -> None:
        """The user has done what the prompt asked (e.g. moved the camera)."""
        self._proceed.set()

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
            self._update(status="cancelled", message="stopped; progress was saved",
                         prompt=None)
        except workflow.WorkflowError as e:
            self._update(status="error", error=str(e), prompt=None)
        except Exception as e:  # noqa: BLE001 - shown in the viewer
            log.exception("job failed")
            self._update(status="error", error=f"{type(e).__name__}: {e}", prompt=None)
        else:
            self._update(status="done", result=result, message="", prompt=None)

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

    def _ask_to_move(self, angle: float) -> None:
        self._proceed.clear()
        self._update(status="waiting", prompt=f"Point the camera at {angle:g}°, then press Continue")
        while not self._proceed.wait(0.2):
            self._check_cancel()
        self._update(status="running", prompt=None)

    def _on_progress(self, angle: float, done: int, total: int, i: int, entry: dict) -> None:
        self._check_cancel()
        with self._lock:
            self._state["progress"] = {"angle": angle, "done": done, "total": total, "led": i}
        self._emit()

    def _on_angle(self, angle: float, result) -> None:
        with self._lock:
            self._state["angles"].append({"angle": angle, **result.counts()})
        self._emit(force=True)

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
        cfg = self.cfg
        angles = p.get("angles") or cfg.scan.angles
        if not isinstance(angles, list) or not all(
            isinstance(a, (int, float)) and not isinstance(a, bool) for a in angles
        ):
            raise workflow.WorkflowError("angles must be a list of degrees")
        leds = workflow.parse_led_subset(p.get("leds"), cfg.led_count)
        fresh = bool(p.get("fresh", False))
        flash = p.get("flash", 1.5)
        if isinstance(flash, bool) or not isinstance(flash, (int, float)) or not 0 <= flash <= 10:
            raise workflow.WorkflowError("flash must be 0-10 seconds")

        def run() -> dict:
            workflow.ensure_sim_tree(cfg)
            self._with_output(lambda out: workflow.run_scan(
                cfg, out, [float(a) for a in angles], leds, fresh=fresh, flash_s=float(flash),
                ask_to_move=self._ask_to_move, on_progress=self._on_progress,
                on_angle=self._on_angle,
            ))
            return {"coverage": workflow.coverage(cfg)}

        return run

    def _prepare_reconstruct(self, p: dict) -> Callable[[], dict]:
        def run() -> dict:
            return workflow.reconstruction_summary(*workflow.rebuild_map(self.cfg))

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

    def _prepare_rescan(self, p: dict) -> Callable[[], dict]:
        index = self._index(p)

        def run() -> dict:
            self._with_output(lambda out: workflow.rescan_led(
                self.cfg, out, index, ask_to_move=self._ask_to_move,
                on_progress=self._on_progress, on_angle=self._on_angle,
            ))
            return self._rebuilt(index)

        return run

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
        tree_map, rec, scans = workflow.rebuild_map(self.cfg)
        return {"index": index, "status": str(tree_map.status[index]),
                **workflow.reconstruction_summary(tree_map, rec, scans)}
