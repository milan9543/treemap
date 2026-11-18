"""The effects engine: renders the current effect at a fixed frame rate to an LedOutput.

It runs on a background thread so it can be driven from the CLI or from the viewer
server. Switching effects crossfades; parameters and brightness can change while it
runs; stopping turns the LEDs off and closes the output.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from treemap.effects import Effect, EffectContext, create_effect
from treemap.outputs.base import LedOutput

log = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        output_factory: Callable[[], LedOutput],
        ctx: EffectContext,
        fps: float = 40.0,
        brightness: float = 1.0,
        crossfade_s: float = 0.6,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.output_factory = output_factory
        self.ctx = ctx
        self.fps = fps
        self.brightness = brightness
        self.crossfade_s = crossfade_s
        self.on_change = on_change
        self.error: str | None = None
        self.frames = 0

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._exiting = False  # the render thread is leaving its loop (guarded by _lock)
        self._current: Effect | None = None
        self._current_t0 = 0.0
        self._previous: Effect | None = None
        self._previous_t0 = 0.0
        self._fade_t0 = 0.0

    # -- control (any thread) ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def effect(self) -> Effect | None:
        return self._current

    def start(self, name: str, params: dict[str, Any] | None = None) -> Effect:
        """Run an effect, crossfading from the current one. Raises KeyError/ParamError."""
        effect = create_effect(name, self.ctx, params)
        now = time.perf_counter()
        with self._lock:
            if self._current is not None and self.crossfade_s > 0:
                self._previous, self._previous_t0 = self._current, self._current_t0
                self._fade_t0 = now
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
            return {
                "running": cur.name if cur else None,
                "params": cur.param_values() if cur else None,
                "brightness": self.brightness,
                "fps": self.fps,
                "error": self.error,
            }

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
                a = (now - self._fade_t0) / self.crossfade_s
                if a >= 1:
                    self._previous = None
                else:
                    old = np.asarray(
                        self._previous.render(now - self._previous_t0), dtype=np.float32
                    )
                    frame = old * (1 - a) + frame * a
        frame = frame * self.brightness
        return np.clip(frame + 0.5, 0, 255).astype(np.uint8)

    def _loop(self, stop: threading.Event) -> None:
        try:
            output = self.output_factory()
        except Exception as e:  # noqa: BLE001 - reported to the caller via state()
            self._fail(str(e))
            return
        period = 1.0 / self.fps
        deadline = time.perf_counter()
        try:
            while not stop.is_set():
                frame = self.render_frame(time.perf_counter())
                if frame is None:
                    break
                output.show(frame)
                self.frames += 1
                deadline += period
                delay = deadline - time.perf_counter()
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
