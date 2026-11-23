"""The effects engine: renders the current effect at a fixed frame rate to an LedOutput.

It runs on a background thread so it can be driven from the CLI or from the viewer
server. Switching effects crossfades; parameters, brightness and the map the 3D effects
use can change while it runs; stopping turns the LEDs off and closes the output.

Each frame is crossfaded, scaled by the brightness, then gamma-corrected: LEDs are
linear, so without it the dim half of every fade looks too bright on a real tree.
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from treemap.effects import Effect, EffectContext, MapEffect, create_effect
from treemap.outputs.base import LedOutput

log = logging.getLogger(__name__)

TIMING_WINDOW_S = 2.0  # timing() describes the last this many seconds
SLOW = 0.9  # warn below this share of the target frame rate


class Engine:
    def __init__(
        self,
        output_factory: Callable[[], LedOutput],
        ctx: EffectContext,
        fps: float = 40.0,
        brightness: float = 1.0,
        crossfade_s: float = 0.6,
        gamma: float = 1.0,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.output_factory = output_factory
        self.ctx = ctx
        self.fps = fps
        self.brightness = brightness
        self.crossfade_s = crossfade_s
        self.on_change = on_change
        self.gamma = gamma
        self._lut = None if gamma == 1 else np.round(
            255 * (np.arange(256) / 255) ** gamma).astype(np.uint8)
        self.error: str | None = None
        self.frames = 0
        # Per frame, for timing(): (start, render s, send s, late). Late: the frame was
        # due before the previous one finished, so the engine can't keep its frame rate.
        self._samples: collections.deque[tuple[float, float, float, bool]] = \
            collections.deque(maxlen=int(fps * TIMING_WINDOW_S * 2) + 8)
        self._slow_warned = False

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._exiting = False  # the render thread is leaving its loop (guarded by _lock)
        self._current: Effect | None = None
        self._current_t0 = 0.0
        self._previous: Effect | None = None
        self._previous_t0 = 0.0
        self._fade_t0 = 0.0
        self._fade_s = crossfade_s

    # -- control (any thread) ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def effect(self) -> Effect | None:
        return self._current

    def start(self, name: str, params: dict[str, Any] | None = None,
              crossfade_s: float | None = None) -> Effect:
        """Run an effect, crossfading from the current one (for ``crossfade_s``, or the
        engine's own crossfade). Raises KeyError/ParamError."""
        effect = create_effect(name, self.ctx, params)
        fade = self.crossfade_s if crossfade_s is None else crossfade_s
        now = time.perf_counter()
        with self._lock:
            if self._current is not None and fade > 0:
                self._previous, self._previous_t0 = self._current, self._current_t0
                self._fade_t0 = now
                self._fade_s = fade
            else:
                self._previous = None
            self._current, self._current_t0 = effect, now
            self.error = None
            # A thread that has decided to exit won't pick the new effect up: start another.
            if not self.running or self._exiting:
                self._exiting = False
                self._stop = threading.Event()  # per thread, so an old one stays stopped
                self._thread = threading.Thread(
                    target=self._loop, args=(self._stop,), name="engine", daemon=True
                )
                self._thread.start()
        self._changed()
        return effect

    def set_params(self, params: dict[str, Any]) -> None:
        """Change the running effect's parameters. Raises ParamError, LookupError."""
        with self._lock:
            if self._current is None:
                raise LookupError("no effect is running")
            self._current.set_params(params)
        self._changed()

    def set_brightness(self, value: float) -> None:
        if not 0 <= value <= 1:
            raise ValueError("brightness must be 0-1")
        self.brightness = float(value)
        self._changed()

    def set_map(self, choice: str) -> None:
        """Switch the map the 3D effects use (see ``treemap.mapping.source.MapSource``).
        Raises LookupError, or ValueError for an unknown choice."""
        source = self.ctx.tree_map
        if not hasattr(source, "select"):
            raise LookupError("this engine has a single map")
        with self._lock:
            before = source.choice
            source.select(choice)
            if isinstance(self._current, MapEffect) and source() is None:
                message = source.missing()  # for the new choice
                source.select(before)  # keep the running effect lit
                raise LookupError(message)
        self._changed()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop, turn the LEDs off and close the output."""
        with self._lock:
            self._exiting = True
            self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        with self._lock:
            was_running = self._current is not None
            self._current = self._previous = None
        if was_running:
            self._changed()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the engine stops (e.g. after an error). True if it stopped."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def state(self) -> dict[str, Any]:
        with self._lock:
            cur = self._current
            source = self.ctx.tree_map
            return {
                "running": cur.name if cur else None,
                "params": cur.param_values() if cur else None,
                "brightness": self.brightness,
                "fps": self.fps,
                "map": getattr(source, "choice", None),
                "maps": getattr(source, "choices", []),
                "error": self.error,
            }

    def timing(self) -> dict[str, Any]:
        """How the last couple of seconds went: frames per second actually sent, the
        time to render a frame and to send it, the gap from one frame to the next (each
        median and worst, ms), and how many frames were late. ``slow`` is True when the
        frame rate falls short. A worst gap well over the frame period with a good frame
        rate means the computer paused the engine now and then."""
        now = time.perf_counter()
        recent = [s for s in list(self._samples) if s[0] >= now - TIMING_WINDOW_S]
        if not self.running or len(recent) < 2:
            return {"fps_target": self.fps, "fps": None, "render_ms": None, "send_ms": None,
                    "gap_ms": None, "late": 0, "slow": False}
        span = max(recent[-1][0] - recent[0][0], 1e-6)
        fps = (len(recent) - 1) / span

        def ms(values: list[float]) -> dict[str, float]:
            v = sorted(values)
            return {"median": round(v[len(v) // 2] * 1000, 2), "max": round(v[-1] * 1000, 2)}

        return {
            "fps_target": self.fps,
            "fps": round(fps, 1),
            "render_ms": ms([s[1] for s in recent]),
            "send_ms": ms([s[2] for s in recent]),
            "gap_ms": ms([b[0] - a[0] for a, b in zip(recent, recent[1:])]),
            "late": sum(s[3] for s in recent),
            "slow": span >= TIMING_WINDOW_S * 0.75 and fps < SLOW * self.fps,
        }

    def _check_pace(self) -> None:
        """Log once when the frame rate falls short, and say why."""
        t = self.timing()
        if t["slow"] and not self._slow_warned:
            self._slow_warned = True
            r, s, budget = t["render_ms"]["median"], t["send_ms"]["median"], 1000 / self.fps
            why = ("rendering" if r > s else "sending") if r + s > 0.8 * budget else \
                "the computer (frames start late: is it busy?)"
            log.warning("effects run at %.1f of %g fps: render %.1f ms, send %.1f ms, "
                        "budget %.1f ms a frame; the bottleneck is %s",
                        t["fps"], self.fps, r, s, budget, why)
        elif not t["slow"] and t["fps"] is not None and t["fps"] >= self.fps * 0.97:
            self._slow_warned = False

    # -- render loop (engine thread) --------------------------------------------------

    def render_frame(self, now: float) -> np.ndarray | None:
        """The output frame at ``now`` (perf_counter time), or None if nothing runs."""
        with self._lock:
            cur = self._current
            if cur is None:
                self._exiting = True
                return None
            frame = np.asarray(cur.render(now - self._current_t0), dtype=np.float32)
            if self._previous is not None:
                a = (now - self._fade_t0) / self._fade_s
                if a >= 1:
                    self._previous = None
                else:
                    old = np.asarray(
                        self._previous.render(now - self._previous_t0), dtype=np.float32
                    )
                    frame = old * (1 - a) + frame * a
        frame = np.clip(frame * self.brightness + 0.5, 0, 255).astype(np.uint8)
        return frame if self._lut is None else self._lut[frame]

    def _loop(self, stop: threading.Event) -> None:
        try:
            output = self.output_factory()
        except Exception as e:  # noqa: BLE001 - reported to the caller via state()
            self._fail(str(e))
            return
        period = 1.0 / self.fps
        deadline = time.perf_counter()
        self._samples.clear()
        try:
            while not stop.is_set():
                t0 = time.perf_counter()
                frame = self.render_frame(t0)
                if frame is None:
                    break
                t1 = time.perf_counter()
                output.show(frame)
                t2 = time.perf_counter()
                self.frames += 1
                deadline += period
                delay = deadline - t2
                self._samples.append((t0, t1 - t0, t2 - t1, delay <= 0))
                if self.frames % int(max(self.fps, 1)) == 0:  # about once a second
                    self._check_pace()
                if delay > 0:
                    stop.wait(delay)
                else:
                    deadline = time.perf_counter()  # fell behind; don't try to catch up
        except Exception as e:  # noqa: BLE001
            name = self._current.name if self._current else "effect"
            log.exception("engine stopped: %s failed", name)
            self._fail(f"{name} failed: {e}")
        finally:
            try:
                output.off()
            except Exception:  # noqa: BLE001 - best effort
                log.warning("could not turn the LEDs off", exc_info=True)
            finally:
                output.close()

    def _fail(self, message: str) -> None:
        with self._lock:
            self._current = self._previous = None
            self._exiting = True
            self.error = message
        self._changed()

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001
                log.exception("engine on_change callback failed")
