"""Simple test patterns for checking wiring and index order (``treemap test ...``)."""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable, Iterable, Iterator

import numpy as np

from treemap.outputs.base import LedOutput

RGB = tuple[int, int, int]

NAMED_COLORS: dict[str, RGB] = {
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 200, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "orange": (255, 100, 0),
    "warm": (255, 160, 60),
}


def parse_color(text: str) -> RGB:
    """Parse ``red``, ``#ff8800``, ``ff8800`` or ``255,136,0``."""
    s = text.strip().lower()
    if s in NAMED_COLORS:
        return NAMED_COLORS[s]
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) == 3 and all(p.isdigit() and int(p) <= 255 for p in parts):
            return (int(parts[0]), int(parts[1]), int(parts[2]))
    else:
        h = s.removeprefix("#")
        if len(h) == 6 and all(c in "0123456789abcdef" for c in h):
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    raise ValueError(
        f"can't parse colour {text!r}; use a name ({', '.join(NAMED_COLORS)}), "
        "#rrggbb or r,g,b"
    )


def black(n: int) -> np.ndarray:
    return np.zeros((n, 3), dtype=np.uint8)


def single(n: int, index: int, rgb: RGB) -> np.ndarray:
    frame = black(n)
    frame[index] = rgb
    return frame


def chase_frames(n: int, rgb: RGB, width: int = 1) -> Iterable[tuple[int, np.ndarray]]:
    """Yield ``(head_index, frame)`` with a block of ``width`` LEDs running 0 → n-1.

    The LEDs behind the head fade so the direction of travel is visible.
    """
    tail = np.linspace(1.0, 0.25, max(width, 1))
    color = np.asarray(rgb, dtype=np.float64)
    for head in range(n):
        frame = black(n)
        for k, level in enumerate(tail):
            if head - k >= 0:
                frame[head - k] = (color * level).astype(np.uint8)
        yield head, frame


def play(
    output: LedOutput,
    frames: Iterable[tuple[int, np.ndarray]],
    fps: float,
    on_frame: Callable[[int], None] | None = None,
) -> None:
    """Show frames at a steady rate (drift-free: sleeps to absolute deadlines)."""
    period = 1.0 / fps
    deadline = time.perf_counter()
    for i, frame in frames:
        output.show(frame)
        if on_frame:
            on_frame(i)
        deadline += period
        delay = deadline - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        else:
            deadline = time.perf_counter()  # fell behind; don't try to catch up


@contextlib.contextmanager
def showing(output: LedOutput, frame: np.ndarray, refresh_s: float = 1.0) -> Iterator[None]:
    """Keep ``frame`` on the LEDs in the background (e.g. while waiting for input)."""
    stop = threading.Event()

    def run() -> None:
        while True:
            output.show(frame)
            if stop.wait(refresh_s):
                return

    thread = threading.Thread(target=run, name="showing", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def hold(
    output: LedOutput, frame: np.ndarray, seconds: float | None = None, refresh_s: float = 1.0
) -> None:
    """Keep showing ``frame`` until ``seconds`` pass (forever if None).

    The frame is re-sent every ``refresh_s`` because WLED drops back to its own effect a
    few seconds after realtime data stops arriving.
    """
    end = None if seconds is None else time.monotonic() + seconds
    while True:
        output.show(frame)
        now = time.monotonic()
        if end is not None and now >= end:
            return
        time.sleep(refresh_s if end is None else min(refresh_s, end - now))
