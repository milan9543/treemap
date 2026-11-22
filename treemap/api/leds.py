"""``POST /leds``: test patterns on the real LEDs, for the page's wiring check.

One command shows at a time; a new one replaces it. A still frame is shown once (the
WLED output re-sends it to keep WLED in realtime mode); the chase runs on a thread.

Commands (JSON), ``color`` being a name, ``#rrggbb`` or ``[r, g, b]``:

* ``{"mode": "off"}``
* ``{"mode": "white", "level": 96}``: every LED white, level 1-255
* ``{"mode": "solid", "color": "red"}``
* ``{"mode": "led", "index": 12, "color": "white"}``: one LED, the rest off; with
  ``"to": 15``, LEDs 12 to 15; with ``"neighbours": true``, the two LEDs either side
  glow dim white, to show where on the strip it is
* ``{"mode": "chase", "color": "white", "width": 3, "speed": 20, "loop": false}``: a
  light running from LED 0 to the last, ``speed`` LEDs a second
* ``{"mode": "status"}``: every LED in its map status colour (green ok, yellow
  interpolated, red failed)
* ``{"mode": "stripe", "front_deg": 40, "width_deg": 30, "color": "white"}``: a tree
  map's front, as a vertical stripe of LEDs facing that way (``front_deg`` as in the
  map's ``orientation``; without it, the map's own front)
* ``{"mode": "edge", "rotate_deg": 90, "mirror": false}``: a flat map's bottom edge in
  white and its left side in red, as they'd be with that orientation (without one,
  the map's own)

The last three need a map for these LEDs.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

import numpy as np

from treemap.mapping.model import TreeMap
from treemap.mapping.quality import NEIGHBOUR_LEVELS, status_frame
from treemap.outputs.base import LedOutput
from treemap.patterns import black, chase_frames, parse_color

MODES = ("off", "white", "solid", "led", "chase", "status", "stripe", "edge")
EDGE = 0.12  # the share of the layout's height (width) lit as its bottom (left) edge
TRUNK = 0.15  # LEDs this close to the trunk (share of the widest) have no clear angle


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


def _turned(tree_map: TreeMap, cmd: dict, keys: tuple[str, ...]) -> TreeMap:
    """The map facing the way the command asks (as saved, if it doesn't say)."""
    asked = {k: cmd[k] for k in keys if k in cmd}
    if not asked:
        return tree_map
    try:
        return tree_map.turned(asked)
    except ValueError as e:
        raise CommandError(str(e)) from None


def stripe_frame(tree_map: TreeMap, width_deg: float, rgb) -> np.ndarray:
    """The LEDs facing the front, ``width_deg`` wide round the trunk."""
    g = tree_map.geometry
    reach = float(g.r[g.valid].max()) if g.valid.any() else 0.0
    lit = g.valid & (np.abs(np.degrees(g.theta)) <= width_deg / 2) & (g.r > TRUNK * reach)
    frame = black(tree_map.led_count)
    frame[lit] = rgb
    return frame


def edge_frame(tree_map: TreeMap) -> np.ndarray:
    """The bottom edge white and the left side red (the left wins in the corner)."""
    g = tree_map.geometry
    span = np.maximum(g.hi - g.lo, 1e-6)
    near = (g.xyz - g.lo) / span  # 0 at the bottom (left), 1 at the top (right)
    frame = black(tree_map.led_count)
    frame[g.valid & (near[:, 1] <= EDGE)] = (200, 200, 200)
    frame[g.valid & (near[:, 0] <= EDGE)] = (255, 0, 0)
    return frame


class LedCommands:
    def __init__(self, output: LedOutput, load_map: Callable[[], TreeMap]) -> None:
        self.output = output
        self.n = output.led_count
        self.load_map = load_map  # the current map; raises CommandError if there isn't one
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
            first = _int(cmd, "index", 0, 0, self.n - 1)
            last = _int(cmd, "to", first, first, self.n - 1)
            neighbours = cmd.get("neighbours", False)
            if not isinstance(neighbours, bool):
                raise CommandError("neighbours must be true or false")
            frame = black(self.n)
            if neighbours:
                for dist, level in enumerate(NEIGHBOUR_LEVELS, 1):
                    for j in (first - dist, last + dist):
                        if 0 <= j < self.n:
                            frame[j] = level
            frame[first:last + 1] = _color(cmd.get("color", "white"))
        elif mode == "status":
            frame = status_frame(self.load_map())
        elif mode == "stripe":
            tree_map = self.load_map()
            if tree_map.shape != "tree":
                raise CommandError("the map is of a flat layout: show its edge instead")
            frame = stripe_frame(_turned(tree_map, cmd, ("front_deg",)),
                                 _number(cmd, "width_deg", 30, 2, 180),
                                 _color(cmd.get("color", "white")))
        elif mode == "edge":
            tree_map = self.load_map()
            if tree_map.shape != "flat":
                raise CommandError("the map is of a tree: show its front (stripe) instead")
            frame = edge_frame(_turned(tree_map, cmd, ("rotate_deg", "mirror")))
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
