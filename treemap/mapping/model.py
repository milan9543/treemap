"""``tree_map.json``: where each LED is, normalised, with how sure we are.

Coordinates: y runs 0 (lowest LED) to 1 (highest), x and z are centred on the trunk
at the same scale, and the axes follow the scan's angle convention (θ = 0 looks from
+z, with +x to the right). Every LED has a status: ``ok`` (measured),
``interpolated`` (filled from its neighbours on the strip) or ``failed`` (a rough
guess). A position is null only when there was nothing to guess from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np

FORMAT_VERSION = 1
STATUSES = ("ok", "interpolated", "failed")


@dataclass(frozen=True)
class Geometry:
    """A map's positions in the forms effects use, as float32 arrays of length N.

    Rows without a position (``valid`` False) hold zeros, so effects can compute on every
    LED without NaN warnings and black the invalid ones out at the end.

    - ``xyz``: the map's coordinates (y up, 0 at the lowest LED, 1 at the highest).
    - ``r``, ``theta``, ``h``: cylindrical round the trunk. ``theta`` is 0 at the front
      (+z, where the first scan angle looks from) and grows towards +x, in -π..π.
    - ``u``, ``v``: the front view, 0-1: u left to right across the widest LED, v = h.
    - ``lo``, ``hi``: the (3,) bounding box of the valid LEDs.
    """

    valid: np.ndarray
    xyz: np.ndarray
    r: np.ndarray
    theta: np.ndarray
    h: np.ndarray
    u: np.ndarray
    v: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    status: np.ndarray

    @classmethod
    def of(cls, positions: np.ndarray, status: np.ndarray) -> Geometry:
        valid = np.isfinite(positions).all(axis=1)
        xyz = np.where(valid[:, None], positions, 0.0).astype(np.float32)
        x, y, z = xyz.T
        r = np.hypot(x, z)
        r_max = float(r[valid].max()) if valid.any() else 0.0
        u = 0.5 + x / (2 * r_max) if r_max > 0 else np.full_like(x, 0.5)
        lo = xyz[valid].min(axis=0) if valid.any() else np.zeros(3, np.float32)
        hi = xyz[valid].max(axis=0) if valid.any() else np.zeros(3, np.float32)
        return cls(valid, xyz, r, np.arctan2(x, z), y.copy(), u.astype(np.float32), y.copy(),
                   lo, hi, status)


@dataclass
class TreeMap:
    positions: np.ndarray  # (N, 3), NaN rows where unknown
    status: np.ndarray  # (N,) str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def led_count(self) -> int:
        return len(self.positions)

    @cached_property
    def geometry(self) -> Geometry:
        """Cylindrical and front-view coordinates for effects (computed once per map)."""
        return Geometry.of(self.positions, self.status)

    def counts(self) -> dict[str, int]:
        return {s: int((self.status == s).sum()) for s in STATUSES}

    def indices(self, status: str) -> list[int]:
        return np.flatnonzero(self.status == status).tolist()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "led_count": self.led_count,
            "counts": self.counts(),
            **self.meta,
            "positions": [
                [round(float(c), 5) for c in p] if np.isfinite(p).all() else None
                for p in self.positions
            ],
            "status": self.status.tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TreeMap:
        if d.get("version") != FORMAT_VERSION:
            raise ValueError(f"unsupported tree map version {d.get('version')!r}; rerun reconstruct")
        positions = np.array(
            [p if p is not None else [np.nan] * 3 for p in d["positions"]], dtype=float
        ).reshape(-1, 3)
        status = np.array(d["status"], dtype="<U12")
        if len(status) != len(positions):
            raise ValueError("positions and status differ in length")
        reserved = {"version", "led_count", "counts", "positions", "status"}
        return cls(positions, status, {k: v for k, v in d.items() if k not in reserved})

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), separators=(",", ":")))
        tmp.replace(path)  # atomic, so the viewer never reads a half-written file

    @classmethod
    def load(cls, path: str | Path) -> TreeMap:
        return cls.from_dict(json.loads(Path(path).read_text()))


class MapFile:
    """The tree map at ``path``, reloaded when the file changes. Calling it returns the
    current :class:`TreeMap`, or None if there isn't a readable one."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._stamp: int | None = None
        self._map: TreeMap | None = None

    def __call__(self) -> TreeMap | None:
        try:
            stamp = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            self._stamp, self._map = None, None
            return None
        if stamp != self._stamp:
            try:
                self._map = TreeMap.load(self.path)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                self._map = None
            self._stamp = stamp
        return self._map
