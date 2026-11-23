"""Seeded random flat layouts: LED strips laid on the floor or fixed to a wall.

The counterpart of :mod:`treemap.sim.tree` for ``shape: flat``. The strips are joined end
to end, as you'd plug one into the next, and laid along one path:

* **rows**: back and forth in rows, turning round at each end, like a sign or a curtain
* **spiral**: round and round from the middle out

Laid by hand, so the path wobbles a little and each LED sits a few millimetres off it.
Neighbouring rows (or turns) stay ``gap`` apart, at least twice the LED spacing, so a
camera can tell them apart.

Coordinates are metres, as for the tree: x across, y up, z towards the camera. The layout
stands upright like a picture on a wall, its lowest LED ``BASE`` above the floor.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from treemap.sim.tree import (
    JITTER,
    LIMITS,
    MAX_SEED,
    PITCH_RANGE,
    SpecError,
    StripSpec,
    random_seed,
    split_counts,
)

FORMAT_VERSION = 1
PATTERNS = ("auto", "rows", "spiral")
GAP_RANGE = (0.07, 0.13)  # m between rows or turns, random when unspecified
ASPECT_RANGE = (1.1, 1.8)  # width / height of rows, random when the width is unspecified
FLAT_LIMITS = {"width": (0.2, 6.0), "gap": (0.02, 0.5)}
STACK_GAP = 0.06  # m of path between one strip's last LED and the next one's first
BASE = 0.5  # m: the lowest LED's height off the floor
WOBBLE = 0.008  # m: how far the hand-laid path strays from the ideal one


@dataclass
class FlatSpec:
    strips: list[StripSpec] = field(default_factory=lambda: [StripSpec(200), StripSpec(200)])
    pattern: str = "auto"  # rows | spiral | auto (either, from the seed)
    width: float | None = None  # m across the rows (rows only); None = random
    gap: float | None = None  # m between rows or spiral turns; None = random
    quirks: bool = True  # let "auto" strip starts reverse some strips
    seed: int | None = None

    @classmethod
    def uniform(cls, led_count: int = 400, n_strips: int = 2, **kw: Any) -> FlatSpec:
        if n_strips < 1 or led_count < n_strips:
            raise SpecError("need at least one strip and one LED per strip")
        return cls(strips=[StripSpec(n) for n in split_counts(led_count, n_strips)], **kw)

    @property
    def led_count(self) -> int:
        return sum(s.leds for s in self.strips)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Any) -> FlatSpec:
        if not isinstance(d, dict):
            raise SpecError("spec must be an object")
        unknown = set(d) - {"strips", "pattern", "width", "gap", "quirks", "seed"}
        if unknown:
            raise SpecError(f"unknown spec field(s): {', '.join(sorted(unknown))}")
        strips = []
        for i, s in enumerate(d.get("strips", [{"leds": 200}, {"leds": 200}])):
            if not isinstance(s, dict) or set(s) - {"leds", "length", "start"}:
                raise SpecError(f"strip {i + 1}: expected {{leds, length, start}}")
            strips.append(StripSpec(s.get("leds"), s.get("length"), s.get("start", "auto")))
        spec = cls(strips=strips, pattern=d.get("pattern", "auto"), width=d.get("width"),
                   gap=d.get("gap"), quirks=d.get("quirks", True), seed=d.get("seed"))
        spec.validate()
        return spec

    def validate(self) -> None:
        lo, hi = LIMITS["strips"]
        if not isinstance(self.strips, list) or not lo <= len(self.strips) <= hi:
            raise SpecError(f"number of strips must be {lo:g}-{hi:g}")
        for i, s in enumerate(self.strips, 1):
            if isinstance(s.leds, bool) or not isinstance(s.leds, int):
                raise SpecError(f"strip {i} LEDs must be a whole number")
            _in(s.leds, *LIMITS["leds"], f"strip {i} LEDs")
            if s.length is not None:
                if isinstance(s.length, bool) or not isinstance(s.length, (int, float)):
                    raise SpecError(f"strip {i} length must be a number")
                _in(s.length / s.leds, *LIMITS["spacing"], f"strip {i} LED spacing")
            if s.start not in ("auto", "bottom", "top"):
                raise SpecError(f"strip {i} start must be auto, bottom or top")
        _in(self.led_count, *LIMITS["total_leds"], "total LEDs")
        if self.pattern not in PATTERNS:
            raise SpecError(f"pattern must be one of {', '.join(PATTERNS)}")
        for key in ("width", "gap"):
            v = getattr(self, key)
            if v is not None:
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise SpecError(f"{key} must be a number")
                _in(v, *FLAT_LIMITS[key], key)
        if not isinstance(self.quirks, bool):
            raise SpecError("quirks must be true or false")
        if self.seed is not None and (isinstance(self.seed, bool) or not isinstance(self.seed, int)
                                      or not 0 <= self.seed <= MAX_SEED):
            raise SpecError(f"seed must be a whole number 0-{MAX_SEED}")


@dataclass
class FlatStrand:
    """A strip occupying global indices ``[start, start + count)``."""

    start: int
    count: int
    spacing: float  # m between neighbouring LEDs
    reversed: bool  # its LED 0 is at the far end of its stretch of the path


@dataclass
class SimFlat:
    seed: int
    pattern: str  # rows | spiral
    width: float  # m: the layout's extent
    height: float
    gap: float  # m between rows or turns
    strands: list[FlatStrand]
    positions: np.ndarray  # (led_count, 3) metres, z = 0
    spec: FlatSpec = field(default_factory=FlatSpec)

    shape = "flat"

    @property
    def led_count(self) -> int:
        return len(self.positions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "shape": "flat",
            "seed": self.seed,
            "pattern": self.pattern,
            "width": round(self.width, 4),
            "height": round(self.height, 4),
            "gap": round(self.gap, 4),
            "led_count": self.led_count,
            "strands": [{**asdict(s), "spacing": round(s.spacing, 5)} for s in self.strands],
            "spec": self.spec.to_dict(),
            "positions": np.round(self.positions, 4).tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SimFlat:
        if d.get("version") != FORMAT_VERSION or d.get("shape") != "flat":
            raise ValueError("not a flat layout of a version this treemap reads")
        positions = np.asarray(d["positions"], dtype=np.float64)
        if positions.ndim != 2 or positions.shape[1] != 3:
            raise ValueError(f"positions must be (N, 3), got {positions.shape}")
        return cls(seed=int(d["seed"]), pattern=str(d["pattern"]), width=float(d["width"]),
                   height=float(d["height"]), gap=float(d["gap"]),
                   strands=[FlatStrand(**s) for s in d["strands"]], positions=positions,
                   spec=FlatSpec.from_dict(d["spec"]))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), separators=(",", ":")))
        tmp.replace(path)


def generate_flat(spec: FlatSpec | None = None, seed: int | None = None) -> SimFlat:
    """Generate a flat layout; the same spec and seed always give the same one."""
    spec = spec or FlatSpec()
    spec.validate()
    if seed is None:
        seed = spec.seed if spec.seed is not None else random_seed()
    rng = np.random.default_rng(seed)

    # Draw every random value up front, so overriding one keeps the rest for a seed.
    random_spacing = rng.uniform(*PITCH_RANGE)
    gap_roll, aspect_roll, pattern_roll = rng.uniform(*GAP_RANGE), rng.uniform(*ASPECT_RANGE), rng.random()
    wobble_phase = rng.uniform(0, 2 * np.pi, 3)
    reverse_rolls = rng.random(len(spec.strips))

    spacings = [s.spacing if s.spacing is not None else random_spacing for s in spec.strips]
    pattern = spec.pattern if spec.pattern != "auto" else ("spiral" if pattern_roll < 0.35 else "rows")
    gap = spec.gap if spec.gap is not None else max(gap_roll, 2 * max(spacings))
    lengths = [(s.leds - 1) * sp for s, sp in zip(spec.strips, spacings)]
    total = sum(lengths) + STACK_GAP * (len(lengths) - 1)

    # landscape, like the screen it may be shown on: area = length × gap
    width = spec.width if spec.width is not None else math.sqrt(total * gap * aspect_roll)
    path = _rows(total, width, gap) if pattern == "rows" else _spiral(total, gap)
    path = _wobble(path, wobble_phase)
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])

    positions, strands, offset, start = [], [], 0.0, 0
    for k, (s, sp, L) in enumerate(zip(spec.strips, spacings, lengths)):
        at = offset + np.arange(s.leds) * sp
        xy = np.stack([np.interp(at, arc, path[:, 0]), np.interp(at, arc, path[:, 1])], axis=1)
        rev = s.start == "top" or (s.start == "auto" and spec.quirks and reverse_rolls[k] < 0.3)
        if rev:
            xy = xy[::-1]
        positions.append(xy)
        strands.append(FlatStrand(start, s.leds, sp, bool(rev)))
        start += s.leds
        offset += L + STACK_GAP
    xy = np.concatenate(positions) + rng.uniform(-JITTER, JITTER, (start, 2)) * 0.6
    xy[:, 0] -= (xy[:, 0].min() + xy[:, 0].max()) / 2  # centred across
    xy[:, 1] += BASE - xy[:, 1].min()
    pos = np.column_stack([xy, np.zeros(start)])
    return SimFlat(seed=seed, pattern=pattern, width=float(np.ptp(xy[:, 0])),
                   height=float(np.ptp(xy[:, 1])), gap=float(gap), strands=strands,
                   positions=pos, spec=spec)


def _rows(length: float, width: float, gap: float) -> np.ndarray:
    """A path back and forth in rows ``gap`` apart, ``width`` across (U-turns included),
    long enough for ``length`` m, from the bottom left."""
    straight = max(width - gap, gap)
    turn = math.pi * gap / 2
    rows = max(1, math.ceil((length + turn) / (straight + turn)))
    pts: list[np.ndarray] = []
    for r in range(rows):
        y = r * gap
        xs = np.linspace(0, straight, max(int(straight / 0.005), 2))
        pts.append(np.stack([xs if r % 2 == 0 else straight - xs, np.full_like(xs, y)], axis=1))
        if r < rows - 1:  # half circle up to the next row, on the side this row ends on
            a = np.linspace(-math.pi / 2, math.pi / 2, 40)[1:-1]
            cx = straight if r % 2 == 0 else 0.0
            sign = 1 if r % 2 == 0 else -1
            pts.append(np.stack([cx + sign * gap / 2 * np.cos(a), y + gap / 2 + gap / 2 * np.sin(a)], axis=1))
    return np.concatenate(pts)


def _spiral(length: float, gap: float) -> np.ndarray:
    """An Archimedean spiral with turns ``gap`` apart, from near the middle outwards,
    long enough for ``length`` m."""
    b = gap / (2 * math.pi)
    theta0 = 2 * math.pi  # start one turn out: the middle is too tight to lay a strip
    # arc length of r = b·θ is about b·θ²/2
    theta1 = math.sqrt(theta0**2 + 2 * (length + gap) / b) + 0.5
    theta = np.linspace(theta0, theta1, max(int((theta1 - theta0) * 200), 200))
    r = b * theta
    return np.stack([r * np.cos(theta), r * np.sin(theta)], axis=1)


def _wobble(path: np.ndarray, phase: np.ndarray) -> np.ndarray:
    """Push the path a little sideways, smoothly, as a hand-laid strip strays."""
    d = np.gradient(path, axis=0)
    normal = np.stack([-d[:, 1], d[:, 0]], axis=1)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-9)
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
    off = WOBBLE * (0.6 * np.sin(s / 0.31 + phase[0]) + 0.3 * np.sin(s / 0.13 + phase[1])
                    + 0.1 * np.sin(s / 0.07 + phase[2]))
    return path + normal * off[:, None]


def _in(v: float, lo: float, hi: float, name: str) -> None:
    if not lo <= v <= hi:
        raise SpecError(f"{name} must be {lo:g}-{hi:g}, got {v:g}")
