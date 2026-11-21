"""``POST /leds``: test patterns on the real LEDs, for the page's wiring check.

One command shows at a time; a new one replaces it. A still frame is shown once (the
WLED output re-sends it to keep WLED in realtime mode); the chase runs on a thread.

Commands (JSON), ``color`` being a name, ``#rrggbb`` or ``[r, g, b]``:

* ``{"mode": "off"}``
* ``{"mode": "white", "level": 96}``: every LED white, level 1-255
* ``{"mode": "solid", "color": "red"}``
* ``{"mode": "led", "index": 12, "color": "white"}``: one LED, the rest off
* ``{"mode": "chase", "color": "white", "width": 3, "speed": 20, "loop": false}``: a
  light running from LED 0 to the last, ``speed`` LEDs a second
* ``{"mode": "status"}``: every LED in its map status colour (green ok, yellow
  interpolated, red failed)
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

import numpy as np

from treemap.outputs.base import LedOutput
from treemap.patterns import black, chase_frames, parse_color, single

MODES = ("off", "white", "solid", "led", "chase", "status")


class CommandError(ValueError):
    """The command isn't valid; the message says why."""


def _color(value: Any) -> tuple[int, int, int]:
    if isinstance(value, list) and len(value) == 3 and all(
            isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in value):
        return value[0], value[1], value[2]
    if isinstance(value, str):
        try:
            return parse_color(value)
        except ValueError as e:
            raise CommandError(str(e)) from None
    raise CommandError("color must be a name, #rrggbb or [r, g, b] with 0-255 each")


def _int(cmd: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = cmd.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise CommandError(f"{key} must be a whole number {lo}-{hi}")
    return v


def _number(cmd: dict, key: str, default: float, lo: float, hi: float) -> float:
    v = cmd.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise CommandError(f"{key} must be a number {lo:g}-{hi:g}")
    return float(v)


class LedCommands:
    def __init__(self, output: LedOutput, status_frame: Callable[[], np.ndarray]) -> None:
        self.output = output
        self.n = output.led_count
        self.status_frame = status_frame  # the current map's status colours
        self.mode: str | None = None  # what's showing
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run(self, cmd: dict[str, Any], before: Callable[[], None] = lambda: None) -> dict[str, Any]:
        """Show a command (see the module docs). Raises :class:`CommandError`, before
        changing anything; ``before`` runs once the command is known to be valid (to stop
        whatever else is using the LEDs)."""
        mode = cmd.get("mode")
        if mode not in MODES:
            raise CommandError(f"mode must be one of {', '.join(MODES)}")
        frames: Iterable[np.ndarray] | None = None
        fps = 0.0
        if mode == "off":
            frame = black(self.n)
        elif mode == "white":
            frame = np.full((self.n, 3), _int(cmd, "level", 96, 1, 255), np.uint8)
        elif mode == "solid":
            frame = np.tile(np.array(_color(cmd.get("color")), np.uint8), (self.n, 1))
        elif mode == "led":
            if "index" not in cmd:
                raise CommandError("led needs an index")
            frame = single(self.n, _int(cmd, "index", 0, 0, self.n - 1),
                           _color(cmd.get("color", "white")))
        elif mode == "status":
            frame = self.status_frame()
        else:  # chase
            rgb = _color(cmd.get("color", "white"))
            width = _int(cmd, "width", 3, 1, 100)
            fps = _number(cmd, "speed", 20, 0.5, 500)
            loop = cmd.get("loop", False)
            if not isinstance(loop, bool):
                raise CommandError("loop must be true or false")
            frames = self._chase(rgb, width, loop)
        before()
        self.stop()
        self.mode = mode
        if frames is None:
            self.output.show(frame)
            return {"mode": mode}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._play, args=(frames, fps, self._stop),
                                        name="led-chase", daemon=True)
        self._thread.start()
        return {"mode": mode, "seconds": round(self.n / fps, 1)}

    def _chase(self, rgb, width: int, loop: bool) -> Iterable[np.ndarray]:
        while True:
            for _, frame in chase_frames(self.n, rgb, width):
                yield frame
            if not loop:
                return

    def _play(self, frames: Iterable[np.ndarray], fps: float, stop: threading.Event) -> None:
        deadline = time.perf_counter()
        for frame in frames:
            if stop.is_set():
                return
            self.output.show(frame)
            deadline += 1 / fps
            stop.wait(max(deadline - time.perf_counter(), 0))
        self.output.show(black(self.n))
        self.mode = "off"

    @property
    def running(self) -> bool:
        """Whether a moving pattern (the chase) is still playing."""
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        """Stop a moving pattern (a still frame stays until something else shows)."""
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None
