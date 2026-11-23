"""``tree_map.json``: where each LED is, normalised, with how sure we are.

Coordinates: y runs 0 (lowest LED) to 1 (highest), x and z are centred on the trunk
at the same scale, and the axes follow the scan's angle convention (θ = 0 looks from
+z, with +x to the right). Every LED has a status: ``ok`` (measured),
``interpolated`` (filled from its neighbours on the strip) or ``failed`` (a rough
guess). A position is null only when there was nothing to guess from.

Format 2 adds ``orientation``: which way the solved positions face the room, set by the
user after a scan and applied by :meth:`Geometry.of`, so the positions stay as solved
and the orientation can change without scanning again. A tree has ``{"front_deg"}``:
the angle (θ, as solved) that faces the room. A flat layout has ``{"rotate_deg",
"mirror"}``: mirrored left to right first (filmed from behind), then turned
anticlockwise by ``rotate_deg``. Format 1 maps load as facing the way they were solved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np

FORMAT_VERSION = 2
READS = (1, 2)  # formats this code reads
STATUSES = ("ok", "interpolated", "failed")


def _degrees(value: Any) -> float | None:
    """An angle normalised to 0-360 and rounded to a tenth, or None if it isn't one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        return None
    return round(float(value) % 360, 1) % 360


def check_orientation(value: Any, shape: str) -> dict[str, Any]:
    """A valid orientation for a map of ``shape`` (see the module docs), normalised:
    angles to 0-360, rounded to a tenth. Raises ValueError saying what's wrong."""
    if not isinstance(value, dict):
        raise ValueError("orientation must be an object")
    if shape == "flat":
        turn, mirror = _degrees(value.get("rotate_deg", 0)), value.get("mirror", False)
        if set(value) - {"rotate_deg", "mirror"} or turn is None or not isinstance(mirror, bool):
            raise ValueError('a flat map turns by {"rotate_deg": degrees anticlockwise, '
                             '"mirror": true or false}')
        return {"rotate_deg": turn, "mirror": mirror}
    front = _degrees(value.get("front_deg", 0))
    if set(value) - {"front_deg"} or front is None:
        raise ValueError('a tree turns by {"front_deg": the angle that faces the room}')
    return {"front_deg": front}


def orient(positions: np.ndarray, status: np.ndarray, orientation: dict[str, Any] | None,
           shape: str = "tree") -> np.ndarray:
    """``positions`` (N, 3) as they face the room. A tree turns round the trunk, so the
    LEDs at ``front_deg`` come to the front (+z). A flat layout is mirrored and turned,
    then normalised again (y 0-1 over the ok LEDs, x centred on them), as a new scan
    would have made it."""
    if not orientation:
        return positions
    P = np.array(positions, dtype=float)
    if shape == "flat":
        if orientation.get("mirror"):
            P[:, 0] = -P[:, 0]
        a = np.radians(orientation.get("rotate_deg", 0))
        x, y = P[:, 0].copy(), P[:, 1].copy()
        P[:, 0], P[:, 1] = x * np.cos(a) - y * np.sin(a), x * np.sin(a) + y * np.cos(a)
        valid = np.isfinite(P).all(axis=1)
        ref = valid & (status == "ok") if (valid & (status == "ok")).any() else valid
        if ref.any():
            y0, y1 = P[ref, 1].min(), P[ref, 1].max()
            scale = y1 - y0 if y1 > y0 else 1.0
            P = (P - [P[ref, 0].mean(), y0, 0.0]) / scale
        return P
    a = np.radians(orientation.get("front_deg", 0))
    x, z = P[:, 0].copy(), P[:, 2].copy()
    P[:, 0], P[:, 2] = x * np.cos(a) - z * np.sin(a), x * np.sin(a) + z * np.cos(a)
    return P


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
    def of(cls, positions: np.ndarray, status: np.ndarray,
           orientation: dict[str, Any] | None = None, shape: str = "tree") -> Geometry:
        """The geometry of ``positions`` turned to face the room (see :func:`orient`)."""
        positions = orient(positions, status, orientation, shape)
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

    @property
    def shape(self) -> str:
        return self.meta.get("shape", "tree")

    @property
    def orientation(self) -> dict[str, Any] | None:
        return self.meta.get("orientation")

    @cached_property
    def geometry(self) -> Geometry:
        """Cylindrical and front-view coordinates for effects, turned to face the room
        (computed once per map)."""
        return Geometry.of(self.positions, self.status, self.orientation, self.shape)

    def turned(self, orientation: dict[str, Any] | None) -> TreeMap:
        """The same map facing another way (None: as solved). Raises ValueError."""
        meta = {k: v for k, v in self.meta.items() if k != "orientation"}
        if orientation is not None:
            meta["orientation"] = check_orientation(orientation, self.shape)
        return TreeMap(self.positions, self.status, meta)

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
        if d.get("version") not in READS:
            raise ValueError(f"unsupported tree map version {d.get('version')!r}; rerun reconstruct")
        positions = np.array(
            [p if p is not None else [np.nan] * 3 for p in d["positions"]], dtype=float
        ).reshape(-1, 3)
        status = np.array(d["status"], dtype="<U12")
        if len(status) != len(positions):
            raise ValueError("positions and status differ in length")
        reserved = {"version", "led_count", "counts", "positions", "status"}
        meta = {k: v for k, v in d.items() if k not in reserved}
        if meta.get("orientation") is not None:
            meta["orientation"] = check_orientation(meta["orientation"], meta.get("shape", "tree"))
        else:
            meta.pop("orientation", None)
        return cls(positions, status, meta)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), separators=(",", ":")))
        tmp.replace(path)  # atomic, so the viewer never reads a half-written file

    @classmethod
    def load(cls, path: str | Path) -> TreeMap:
        return cls.from_dict(json.loads(Path(path).read_text()))


def saved_orientation(path: str | Path) -> dict[str, Any] | None:
    """The orientation of the map at ``path``, if there's a readable one."""
    try:
        return TreeMap.load(path).orientation
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


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
