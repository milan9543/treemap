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
from pathlib import Path
from typing import Any

import numpy as np

FORMAT_VERSION = 1
STATUSES = ("ok", "interpolated", "failed")


@dataclass
class TreeMap:
    positions: np.ndarray  # (N, 3), NaN rows where unknown
    status: np.ndarray  # (N,) str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def led_count(self) -> int:
        return len(self.positions)

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
