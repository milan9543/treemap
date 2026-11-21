"""How one camera sees the scan code's colours, measured by ``treemap camera check``.

A phone films small, bright LEDs with washed-out colours: JPEG keeps colour at half
resolution, so a tiny green dot arrives as something like (83, 125, 95), and green
light also reaches the sensor's blue and red pixels. Fixed thresholds (the default
:func:`treemap.scan.track.classify`, which suits the simulator's pure colours) then read
many coloured LEDs as white.

So ``camera check`` shows each colour on every LED, measures each one's **chromaticity**
(colour without brightness: ``(r, g, b) / (r + g + b)``) as this camera sees it, and the
scan reads every blob as the nearest measured colour. A blob about as near to two
colours as to one is left unread (-1), which the code's check digit and the votes over
several cycles can cope with better than a wrong reading.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

NAMES = ("red", "green", "blue", "white")  # rows, in symbol order (white = SYNC = 3)
MARGIN = 1.3  # the second-nearest colour must be this much further than the nearest
FORMAT_VERSION = 1


class ColourError(ValueError):
    """A measurement or file that can't give a colour model."""


def chromaticity(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=float).reshape(-1, 3)
    return rgb / np.maximum(rgb.sum(axis=1, keepdims=True), 1e-6)


@dataclass
class ColourModel:
    centres: np.ndarray  # (4, 3) chromaticity of red, green, blue, white
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def fit(cls, samples: dict[str, np.ndarray], **meta: Any) -> ColourModel:
        """From ``{"red": (K, 3) RGB of blobs while every LED was red, ...}``."""
        missing = [n for n in NAMES if len(samples.get(n, ())) == 0]
        if missing:
            raise ColourError(f"no LEDs were seen in {', '.join(missing)}")
        centres = np.array([np.median(chromaticity(samples[n]), axis=0) for n in NAMES])
        return cls(centres, meta)

    def classify(self, rgb: np.ndarray) -> np.ndarray:
        """Symbol of each ``(K, 3)`` RGB colour: 0-3, or -1 if it's unclear."""
        if not len(rgb):
            return np.zeros(0, dtype=int)
        d = np.linalg.norm(chromaticity(rgb)[:, None, :] - self.centres[None], axis=2)
        order = np.argsort(d, axis=1)
        nearest = np.take_along_axis(d, order[:, :2], axis=1)
        return np.where(nearest[:, 1] > MARGIN * nearest[:, 0], order[:, 0], -1)

    def distance(self, a: str, b: str) -> float:
        """How far apart two colours look to this camera (0: the same)."""
        return float(np.linalg.norm(self.centres[NAMES.index(a)] - self.centres[NAMES.index(b)]))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": FORMAT_VERSION,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **self.meta,
            "chromaticity": {n: [round(float(c), 5) for c in row]
                             for n, row in zip(NAMES, self.centres)},
        }
        path.write_text(json.dumps(data, indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> ColourModel:
        try:
            d = json.loads(Path(path).read_text())
            if d.get("version") != FORMAT_VERSION:
                raise ColourError(f"unsupported version {d.get('version')!r}")
            centres = np.array([d["chromaticity"][n] for n in NAMES], dtype=float)
        except (KeyError, TypeError, ValueError) as e:
            raise ColourError(f"{path}: {e}") from None
        if centres.shape != (4, 3) or not np.isfinite(centres).all():
            raise ColourError(f"{path}: chromaticity must be 3 numbers per colour")
        meta = {k: v for k, v in d.items() if k not in ("version", "chromaticity")}
        return cls(centres, meta)
