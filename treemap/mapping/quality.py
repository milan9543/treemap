"""Frames for checking a map on the LEDs themselves: each LED in its status colour."""

from __future__ import annotations

import numpy as np

from treemap.mapping.model import TreeMap

# Moderate levels: every LED lit at once, so keep the power draw down.
STATUS_COLORS: dict[str, tuple[int, int, int]] = {
    "ok": (0, 110, 0),  # green
    "interpolated": (150, 100, 0),  # yellow
    "failed": (170, 0, 0),  # red
}
NEIGHBOUR_LEVELS = (40, 12)  # dim white on the LEDs 1 and 2 away from the one being fixed


def status_frame(tree_map: TreeMap) -> np.ndarray:
    """Every LED in its status colour."""
    frame = np.zeros((tree_map.led_count, 3), dtype=np.uint8)
    for status, rgb in STATUS_COLORS.items():
        frame[tree_map.status == status] = rgb
    return frame
