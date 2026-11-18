"""Compare a reconstructed map with the simulator's ground truth."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from treemap.mapping.model import STATUSES, TreeMap
from treemap.sim.tree import SimTree


@dataclass
class Evaluation:
    errors: np.ndarray  # (N,) distance to the truth as a fraction of the LED height span
    status: np.ndarray  # (N,)
    height_m: float  # the truth's LED height span
    rotation_deg: float  # alignment applied: rotation about the trunk
    scale: float  # and scale (1 = the map's normalisation was spot on)

    def summary(self, which: str | None = None) -> dict[str, float | int]:
        """count, median and p95 error (fraction of height) for one status or all."""
        sel = np.isfinite(self.errors) & (True if which is None else self.status == which)
        e = self.errors[sel]
        if not len(e):
            return {"count": 0, "median": float("nan"), "p95": float("nan")}
        return {"count": int(len(e)), "median": float(np.median(e)),
                "p95": float(np.percentile(e, 95))}

    def table(self) -> list[tuple[str, dict]]:
        return [(s, self.summary(s)) for s in STATUSES] + [("all", self.summary())]


def evaluate(tree_map: TreeMap, tree: SimTree) -> Evaluation:
    """Errors after the best rotation about the trunk, scale and offset (fitted on the
    ok LEDs), so a map that is right up to those differences scores zero."""
    if tree_map.led_count != tree.led_count:
        raise ValueError(
            f"the map has {tree_map.led_count} LEDs but the simulated tree has {tree.led_count}"
        )
    T = tree.positions.astype(float)
    y0, y1 = T[:, 1].min(), T[:, 1].max()
    T = (T - [0.0, y0, 0.0]) / (y1 - y0)  # normalised like the map, trunk at x = z = 0
    M = tree_map.positions
    ok = (tree_map.status == "ok") & np.isfinite(M).all(axis=1)
    if ok.sum() < 3:
        raise ValueError("the map has fewer than 3 ok LEDs")

    a, b = M[ok], T[ok]
    ac, bc = a.mean(axis=0), b.mean(axis=0)
    a0, b0 = a - ac, b - bc
    # rotation about y: (x, z) as complex numbers
    za = a0[:, 0] + 1j * a0[:, 2]
    zb = b0[:, 0] + 1j * b0[:, 2]
    rot = np.angle((np.conj(za) * zb).sum())
    c, s = np.cos(rot), np.sin(rot)
    R = np.array([[c, 0, -s], [0, 1, 0], [s, 0, c]])
    scale = float((b0 * (a0 @ R.T)).sum() / (a0**2).sum())
    aligned = scale * (M - ac) @ R.T + bc
    errors = np.linalg.norm(aligned - T, axis=1)  # NaN where the map has no position
    return Evaluation(errors, tree_map.status, float(y1 - y0), float(np.degrees(rot)), scale)
