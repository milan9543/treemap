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
    rotation_deg: float  # alignment applied: rotation angle
    scale: float  # and scale (1 = the map's normalisation was spot on)
    aligned_m: np.ndarray  # (N, 3) the map's positions moved onto the truth, metres (NaN: none)

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
    """Errors after the best rotation, scale and offset (Umeyama, fitted on the ok LEDs),
    so a map that is right up to those differences scores zero."""
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
    U, S, Vt = np.linalg.svd(b0.T @ a0)
    D = np.diag([1.0, 1.0, np.sign(np.linalg.det(U @ Vt))])  # a rotation, not a mirror
    R = U @ D @ Vt
    scale = float(np.trace(np.diag(S) @ D) / (a0**2).sum())
    aligned = scale * (M - ac) @ R.T + bc
    errors = np.linalg.norm(aligned - T, axis=1)  # NaN where the map has no position
    angle = float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))
    aligned_m = aligned * (y1 - y0) + [0.0, y0, 0.0]
    return Evaluation(errors, tree_map.status, float(y1 - y0), angle, scale, aligned_m)
