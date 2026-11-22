"""Frames for checking a tree map on the tree itself (``treemap show-mapping``, ``fix``)."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from treemap.mapping.model import TreeMap

# Moderate levels: every LED lit at once, so keep the power draw down.
STATUS_COLORS: dict[str, tuple[int, int, int]] = {
    "ok": (0, 110, 0),  # green
    "interpolated": (150, 100, 0),  # yellow
    "failed": (170, 0, 0),  # red
}
# The verify sweep: ok LEDs white, guesses in their status colour.
VERIFY_COLORS: dict[str, tuple[int, int, int]] = {
    "ok": (200, 200, 200),
    "interpolated": (255, 170, 0),
    "failed": (255, 0, 0),
}
FIX_COLOR = (0, 60, 255)  # blue
NEIGHBOUR_LEVELS = (40, 12)  # dim white on the LEDs 1 and 2 away from the one being fixed


def status_frame(tree_map: TreeMap) -> np.ndarray:
    """Every LED in its status colour."""
    frame = np.zeros((tree_map.led_count, 3), dtype=np.uint8)
    for status, rgb in STATUS_COLORS.items():
        frame[tree_map.status == status] = rgb
    return frame


def verify_frame(tree_map: TreeMap, phase: float, band: float = 0.05) -> np.ndarray:
    """One frame of the verify sweep. ``phase`` 0-1 is a horizontal plane rising
    through the tree, 1-2 a vertical one sweeping left to right (as seen from the
    front). ``band`` is the plane's half-thickness as a fraction of the tree's
    height. An LED that lights out of step with its neighbours is in the wrong place.
    """
    g = tree_map.geometry
    axis, f = (1, phase) if phase < 1 else (0, phase - 1)
    coord, valid = g.xyz[:, axis], g.valid
    if not valid.any():
        return np.zeros((tree_map.led_count, 3), dtype=np.uint8)
    lo, hi = coord[valid].min() - 2 * band, coord[valid].max() + 2 * band
    level = lo + min(max(f, 0.0), 1.0) * (hi - lo)
    weight = np.where(valid, np.clip(1 - np.abs(coord - level) / band, 0, 1), 0.0)
    colors = np.zeros((tree_map.led_count, 3), dtype=np.float32)
    for status, rgb in VERIFY_COLORS.items():
        colors[tree_map.status == status] = rgb
    return (colors * weight[:, None]).astype(np.uint8)


def verify_frames(
    tree_map: TreeMap, fps: float = 40.0, seconds: float = 6.0, band: float = 0.05
) -> Iterator[tuple[int, np.ndarray]]:
    """The rise then the sweep (see :func:`verify_frame`), ``seconds`` each, then off."""
    steps = max(int(round(seconds * fps)), 2)
    k = 0
    for half in (0, 1):
        for f in np.linspace(0, 1, steps):
            yield k, verify_frame(tree_map, half + min(f, 0.999999), band)
            k += 1
    yield k, np.zeros((tree_map.led_count, 3), dtype=np.uint8)


def fix_frame(led_count: int, index: int) -> np.ndarray:
    """LED ``index`` blue, its neighbours dimly white so you can see where it sits."""
    frame = np.zeros((led_count, 3), dtype=np.uint8)
    for dist, level in enumerate(NEIGHBOUR_LEVELS, 1):
        for j in (index - dist, index + dist):
            if 0 <= j < led_count:
                frame[j] = level
    frame[index] = FIX_COLOR
    return frame
