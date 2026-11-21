"""Seeded random Christmas tree with LED strips: the simulator's ground truth.

Coordinates are metres: y is up, the trunk runs along the y axis, the floor is y = 0.
Each strip is wound round the cone as a slightly irregular spiral whose depth zig-zags
into and out of the branches, the way you'd wind lights by hand: evenly spaced, never
over other wire. Interleaved strips share the gaps between turns, stacked strips follow
on from each other. LED positions are resampled at the strip's LED spacing along the
wire, so neighbouring LEDs are never further apart than that spacing (plus a little
placement jitter).

What gets generated is described by a :class:`TreeSpec` (strip lengths and LED counts,
tree size, layout). Anything left unset is randomised from the seed. The branches the
LEDs hang on are grown in :mod:`treemap.sim.branches`.
"""

from __future__ import annotations

import json
import math
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from treemap.sim.branches import Branch, grow_branches

if TYPE_CHECKING:
    from treemap.config import Config

FORMAT_VERSION = 3  # 3 added branches; version 2 files get them grown on load
MAX_SEED = 2**31 - 1

HEIGHT_RANGE = (1.5, 2.2)  # m, random height when unspecified
RADIUS_RANGE = (0.5, 0.8)  # m at the base of the cone, random when unspecified
PITCH_RANGE = (0.065, 0.08)  # m, random LED spacing when a strip's length is unspecified
JITTER = 0.005  # m, max per-axis random offset of each LED from the wire

LAYOUTS = ("auto", "interleaved", "stacked")
STARTS = ("auto", "bottom", "top")

# Accepted ranges for user-supplied specs (also served to the viewer for its form).
LIMITS: dict[str, tuple[float, float]] = {
    "strips": (1, 8),
    "leds": (1, 2000),
    "total_leds": (1, 5000),
    "spacing": (0.01, 0.5),  # m between LEDs, i.e. length / leds
    "height": (0.3, 5.0),
    "radius": (0.1, 2.5),
}

# m: widest vertical gap between neighbouring wires (of any strip). A strip too short to
# wind its band that densely covers less height instead of being stretched further.
MAX_TURN_GAP = 0.35
TIGHT_GAP = 0.04  # m: warn when neighbouring wire turns are closer than this
MAX_TURNS = 150
STACK_GAP = 0.1  # m of bare winding between one stacked strip's end and the next's start
WOBBLE_SHARE = 0.15  # the wire's height wobble stays under this share of the gap between turns


class SpecError(ValueError):
    """An invalid :class:`TreeSpec`."""


@dataclass
class StripSpec:
    leds: int
    length: float | None = None  # m of strip; spacing = length / leds. None = random spacing
    start: str = "auto"  # where index 0 is: bottom | top | auto (random top if quirks)

    @property
    def spacing(self) -> float | None:
        return None if self.length is None else self.length / self.leds


@dataclass
class TreeSpec:
    strips: list[StripSpec] = field(default_factory=lambda: [StripSpec(200), StripSpec(200)])
    height: float | None = None  # m, None = random
    radius: float | None = None  # m at the base, None = random
    layout: str = "auto"  # interleaved | stacked | auto (stacked sometimes, if quirks)
    quirks: bool = True  # let "auto" settings pick wiring quirks at random
    seed: int | None = None  # None = random

    @classmethod
    def uniform(cls, led_count: int = 400, n_strips: int = 2, **kw: Any) -> TreeSpec:
        """``led_count`` LEDs split as evenly as possible over ``n_strips`` strips."""
        if n_strips < 1 or led_count < n_strips:
            raise SpecError("need at least one strip and one LED per strip")
        return cls(strips=[StripSpec(n) for n in split_counts(led_count, n_strips)], **kw)

    @property
    def led_count(self) -> int:
        return sum(s.leds for s in self.strips)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Any) -> TreeSpec:
        """Parse and validate a spec from JSON-like data (e.g. sent by the viewer)."""
        if not isinstance(d, dict):
            raise SpecError("spec must be an object")
        unknown = set(d) - {"strips", "height", "radius", "layout", "quirks", "seed"}
        if unknown:
            raise SpecError(f"unknown spec field(s): {', '.join(sorted(unknown))}")
        strips_raw = d.get("strips", [{"leds": 200}, {"leds": 200}])
        if not isinstance(strips_raw, list):
            raise SpecError("strips must be a list")
        strips = []
        for i, s in enumerate(strips_raw):
            if not isinstance(s, dict) or set(s) - {"leds", "length", "start"}:
                raise SpecError(f"strip {i + 1}: expected {{leds, length, start}}")
            strips.append(
                StripSpec(
                    leds=_int(s.get("leds"), f"strip {i + 1} LEDs"),
                    length=_opt_num(s.get("length"), f"strip {i + 1} length"),
                    start=s.get("start", "auto"),
                )
            )
        spec = cls(
            strips=strips,
            height=_opt_num(d.get("height"), "height"),
            radius=_opt_num(d.get("radius"), "radius"),
            layout=d.get("layout", "auto"),
            quirks=d.get("quirks", True),
            seed=None if d.get("seed") is None else _int(d.get("seed"), "seed"),
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        lo, hi = LIMITS["strips"]
        if not lo <= len(self.strips) <= hi:
            raise SpecError(f"number of strips must be {lo:g}-{hi:g}, got {len(self.strips)}")
        for i, s in enumerate(self.strips, 1):
            _in_range(s.leds, "leds", f"strip {i} LEDs")
            if s.length is not None:
                if s.length <= 0:
                    raise SpecError(f"strip {i} length must be positive")
                lo, hi = LIMITS["spacing"]
                if not lo <= s.spacing <= hi:
                    raise SpecError(
                        f"strip {i}: {s.length:g} m for {s.leds} LEDs is "
                        f"{s.spacing * 100:.1f} cm between LEDs; must be "
                        f"{lo * 100:g}-{hi * 100:g} cm"
                    )
            if s.start not in STARTS:
                raise SpecError(f"strip {i} start must be one of {', '.join(STARTS)}")
        _in_range(self.led_count, "total_leds", "total LEDs")
        if self.height is not None:
            _in_range(self.height, "height", "height")
        if self.radius is not None:
            _in_range(self.radius, "radius", "radius")
        if self.layout not in LAYOUTS:
            raise SpecError(f"layout must be one of {', '.join(LAYOUTS)}")
        if not isinstance(self.quirks, bool):
            raise SpecError("quirks must be true or false")
        if self.seed is not None and not 0 <= self.seed <= MAX_SEED:
            raise SpecError(f"seed must be 0-{MAX_SEED}")


def spec_from_config(cfg: Config) -> TreeSpec:
    """The generator spec described by the ``sim`` section of the config."""
    sim = cfg.sim
    if sim.strips is None:
        spec = TreeSpec()
    else:
        spec = TreeSpec(strips=[StripSpec(s.leds, s.length, s.start) for s in sim.strips])
    spec.height, spec.radius, spec.layout = sim.height, sim.radius, sim.layout
    spec.quirks, spec.seed = sim.quirks, sim.seed
    spec.validate()
    return spec


@dataclass
class Strand:
    """A generated strip occupying global indices ``[start, start + count)``."""

    start: int
    count: int
    spacing: float  # m between neighbouring LEDs along the wire
    turns: float  # times the strip winds round the trunk
    coverage: float  # fraction of its height band the strip reaches (< 1: strip too short)
    index_from_top: bool  # strip index 0 is at its upper end
    handedness: str  # "ccw" or "cw", winding direction seen from above


@dataclass
class SimTree:
    seed: int
    height: float
    radius: float
    trunk_radius: float
    layout: str  # "single", "interleaved" (strips share the height) or "stacked"
    strands: list[Strand]
    positions: np.ndarray  # (led_count, 3) float64, metres
    spec: TreeSpec = field(default_factory=TreeSpec)  # what was asked for
    warnings: list[str] = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)

    @property
    def led_count(self) -> int:
        return len(self.positions)

    @property
    def max_spacing(self) -> float:
        return max(s.spacing for s in self.strands)

    def normalised_positions(self) -> np.ndarray:
        """Positions in the tree map's frame: y 0 (lowest LED) to 1 (highest), x and z
        centred on the trunk, all divided by the LEDs' height span."""
        y0, y1 = self.positions[:, 1].min(), self.positions[:, 1].max()
        return (self.positions - [0.0, y0, 0.0]) / (y1 - y0)

    def cone_radius_at(self, y: np.ndarray | float) -> np.ndarray:
        """Outer radius of the foliage cone at height ``y``."""
        return self.radius * np.clip(1.0 - np.asarray(y) / self.height, 0.0, 1.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "seed": self.seed,
            "height": round(self.height, 4),
            "radius": round(self.radius, 4),
            "trunk_radius": round(self.trunk_radius, 4),
            "layout": self.layout,
            "led_count": self.led_count,
            "strands": [
                {**asdict(s), "spacing": round(s.spacing, 5), "turns": round(s.turns, 3),
                 "coverage": round(s.coverage, 3)}
                for s in self.strands
            ],
            "spec": self.spec.to_dict(),
            "warnings": self.warnings,
            "positions": np.round(self.positions, 4).tolist(),
            "branches": [b.to_dict() for b in self.branches],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SimTree:
        if d.get("version") not in (2, FORMAT_VERSION):
            raise ValueError(
                f"unsupported sim tree format version {d.get('version')!r}; "
                "regenerate it with `treemap sim new`"
            )
        positions = np.asarray(d["positions"], dtype=np.float64)
        if positions.ndim != 2 or positions.shape[1] != 3:
            raise ValueError(f"positions must be (N, 3), got {positions.shape}")
        seed, height = int(d["seed"]), float(d["height"])
        radius, trunk_radius = float(d["radius"]), float(d["trunk_radius"])
        if "branches" in d:
            branches = [Branch.from_dict(b) for b in d["branches"]]
        else:
            branches = grow_branches(seed, height, radius, trunk_radius, positions)
        return cls(
            seed=seed,
            height=height,
            radius=radius,
            trunk_radius=trunk_radius,
            layout=str(d["layout"]),
            strands=[Strand(**s) for s in d["strands"]],
            positions=positions,
            spec=TreeSpec.from_dict(d["spec"]),
            warnings=list(d.get("warnings", [])),
            branches=branches,
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), separators=(",", ":")))
        tmp.replace(path)  # atomic, so the viewer never reads a half-written file

    @classmethod
    def load(cls, path: str | Path) -> SimTree:
        return cls.from_dict(json.loads(Path(path).read_text()))


def random_seed() -> int:
    return secrets.randbelow(MAX_SEED) + 1


def split_counts(total: int, parts: int) -> list[int]:
    """Split ``total`` LEDs into ``parts`` strips as evenly as possible."""
    base, extra = divmod(total, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


def generate_tree(spec: TreeSpec | None = None, seed: int | None = None) -> SimTree:
    """Generate a tree. The same spec and seed always give the same tree.

    ``seed`` overrides ``spec.seed``; if both are None a random seed is chosen (and
    recorded in the result). Raises :class:`SpecError` for an invalid spec, including
    strips with more wire than fits on the tree.
    """
    spec = spec or TreeSpec()
    spec.validate()
    if seed is None:
        seed = spec.seed if spec.seed is not None else random_seed()
    rng = np.random.default_rng(seed)

    # Draw every random value unconditionally so overriding one (e.g. height) leaves the
    # rest of the tree the same for a given seed.
    height = _pick(spec.height, rng.uniform(*HEIGHT_RANGE))
    radius = _pick(spec.radius, rng.uniform(*RADIUS_RANGE))
    trunk_radius = min(rng.uniform(0.025, 0.05), radius * 0.1)
    random_spacing = rng.uniform(*PITCH_RANGE)
    y_bottom = height * rng.uniform(0.03, 0.08)  # lowest branches sit above the floor
    y_top = height * rng.uniform(0.93, 0.97)
    direction = 1.0 if rng.random() < 0.5 else -1.0  # same winding for every strip
    stack_roll = rng.random()
    base_phase = rng.uniform(0, 2 * np.pi)

    n = len(spec.strips)
    if n == 1:
        layout = "single"
    elif spec.layout == "auto":
        layout = "stacked" if spec.quirks and stack_roll < 0.35 else "interleaved"
    else:
        layout = spec.layout

    def cone_r(y: np.ndarray) -> np.ndarray:
        return radius * np.clip(1.0 - y / height, 0.0, 1.0)

    # Wire is wound the way you'd do it by hand: evenly, never over itself.
    # Interleaved (and single) strips all follow one winding, spread evenly round the
    # trunk so each runs half way between the others' turns; a shorter strip just ends
    # lower. Stacked strips follow one winding end to end: the next strip carries on a
    # little above where the last one ran out.
    w = _winding(rng)
    spacings = [s.spacing if s.spacing is not None else random_spacing for s in spec.strips]
    lengths = [(s.leds - 1) * sp for s, sp in zip(spec.strips, spacings)]
    jitters = [rng.uniform(-JITTER, JITTER, (s.leds, 3)) for s in spec.strips]
    top_rolls = [rng.random() for _ in spec.strips]
    per_gap = 1 if layout == "stacked" else n  # strips sharing each gap between turns

    def solve(target: float) -> tuple[float, float]:
        return _solve_turns(w, target, y_bottom, y_top, MAX_TURN_GAP * per_gap, per_gap,
                            direction, cone_r, trunk_radius)

    if layout == "stacked":
        try:
            turns, top = solve(sum(lengths) + STACK_GAP * (n - 1))
        except SpecError as e:
            raise SpecError(f"the strips together: {e}") from None
        offsets = np.concatenate([[0.0], np.cumsum([L + STACK_GAP for L in lengths])])[:-1]
        phases = [base_phase] * n
    else:
        needed = []
        for k, L in enumerate(lengths):  # all wind at the pace of the one needing most turns
            try:
                needed.append(solve(L)[0])
            except SpecError as e:
                raise SpecError(f"strip {k + 1}: {e}") from None
        turns, top = max(*needed, (y_top - y_bottom) / (MAX_TURN_GAP * n)), y_top
        offsets = [0.0] * n
        phases = [base_phase + 2 * np.pi * k / n for k in range(n)]
    dense = _path(w, turns, y_bottom, top, per_gap, 0.0, direction, cone_r, trunk_radius)
    reach = (top - y_bottom) / (y_top - y_bottom)  # stacked: how far up they all get

    strands: list[Strand] = []
    chunks: list[np.ndarray] = []
    warnings: list[str] = []
    start = 0
    for k, strip in enumerate(spec.strips):
        pts, strip_turns, (ya, yb) = _along(dense, w, turns, strip.leds, spacings[k],
                                            offsets[k], phases[k], y_bottom, top)
        coverage = reach if layout == "stacked" else (yb - y_bottom) / (y_top - y_bottom)
        coverage = (1.0 if coverage > 0.995 else coverage) if strip.leds > 1 else 0.0
        pts = pts + jitters[k]
        from_top = strip.start == "top" or (
            strip.start == "auto" and spec.quirks and top_rolls[k] < 0.3
        )
        if from_top:
            pts = pts[::-1]
        chunks.append(pts)
        strands.append(
            Strand(
                start=start,
                count=strip.leds,
                spacing=float(spacings[k]),
                turns=float(strip_turns),
                coverage=float(coverage),
                index_from_top=bool(from_top),
                handedness="ccw" if direction > 0 else "cw",
            )
        )
        band = (yb - ya) if layout == "stacked" else (y_top - y_bottom)
        warnings += _strip_warnings(k, strip.leds, spacings[k], strip_turns,
                                    1.0 if layout == "stacked" else coverage, band, layout, n)
        start += strip.leds
    if layout == "stacked" and reach < 0.98:  # (per strip, coverage only means anything
        # for interleaved strips; stacked ones all fall short together)
        warnings.insert(0, (
            f"The strips ({sum(s.leds * sp for s, sp in zip(spec.strips, spacings)):.1f} m "
            f"together) are too short to spiral round the whole tree: they only reach "
            f"{reach:.0%} of the way up."
        ))

    positions = np.concatenate(chunks)
    positions[:, 1] = np.clip(positions[:, 1], 0.0, height)
    return SimTree(
        seed=int(seed),
        height=float(height),
        radius=float(radius),
        trunk_radius=float(trunk_radius),
        layout=layout,
        strands=strands,
        positions=positions,
        spec=spec,
        warnings=warnings,
        branches=grow_branches(seed, height, radius, trunk_radius, positions),
    )


def _strip_warnings(
    k: int, leds: int, spacing: float, turns: float, coverage: float, band: float,
    layout: str, n: int,
) -> list[str]:
    out = []
    length = leds * spacing
    if coverage < 0.98:
        out.append(
            f"Strip {k + 1} ({length:.1f} m) is too short to spiral round its whole "
            f"{'band' if layout == 'stacked' else 'tree'}: it only reaches "
            f"{coverage:.0%} of the way up."
        )
    elif turns > 0:
        gap = band / turns
        if layout == "interleaved":
            gap /= n  # the other strips' turns sit in between
        if gap < TIGHT_GAP:
            out.append(
                f"Strip {k + 1} winds {turns:.0f} times; neighbouring turns are only "
                f"~{gap * 100:.1f} cm apart, so LEDs on different turns will be hard to "
                "tell apart in a scan."
            )
    return out


@dataclass
class _Winding:
    """The random shape of a wire's spiral, all as functions of the angle travelled
    ``a`` (or of ``u``, 0-1 along the strip). Drawn before solving, so the solve is
    deterministic."""

    knot_a: np.ndarray  # depth zig-zag: knots alternate deep (into a branch) and shallow
    knot_depth: np.ndarray
    warp: np.ndarray  # height reached at each sample of u: turns a little irregular
    wob_f: np.ndarray  # gentle height and angle wobble (wire sagging between branches)
    wob_p: np.ndarray
    wob_y: np.ndarray
    wob_a: np.ndarray


SAMPLES = 20000


def _winding(rng: np.random.Generator) -> _Winding:
    max_angle = 2 * np.pi * MAX_TURNS
    gaps = rng.uniform(0.25, 0.7, size=int(max_angle / 0.25) + 2)
    knot_a = np.concatenate([[0.0], np.cumsum(gaps)])
    knot_depth = np.where(
        np.arange(len(knot_a)) % 2 == 0,
        rng.uniform(0.85, 1.0, len(knot_a)),  # out at the branch tips
        rng.uniform(0.35, 0.7, len(knot_a)),  # dipping in towards the trunk
    )
    skip = (np.arange(len(knot_a)) % 2 == 1) & (rng.random(len(knot_a)) < 0.3)
    knot_depth[skip] = rng.uniform(0.8, 0.95, skip.sum())  # sometimes just skims the surface
    # Turn spacing varies a little, as when winding by hand: a smooth monotone warp.
    warp_knots = np.concatenate([[0.0], np.cumsum(rng.gamma(10.0, 1.0, 24))])
    warp_knots /= warp_knots[-1]
    warp = np.interp(np.linspace(0, 1, SAMPLES), np.linspace(0, 1, len(warp_knots)), warp_knots)
    return _Winding(
        knot_a=knot_a, knot_depth=knot_depth, warp=warp,
        wob_f=rng.uniform(0.3, 2.5, 4), wob_p=rng.uniform(0, 2 * np.pi, 4),
        wob_y=rng.uniform(0.004, 0.012, 4), wob_a=rng.uniform(0.02, 0.08, 4),
    )


def _path(w: _Winding, turns: float, y0: float, top: float, per_gap: int, phase: float,
          direction: float, cone_r, trunk_radius: float) -> np.ndarray:
    """The wire's spiral from ``y0`` to ``top`` in ``turns`` turns, densely sampled."""
    u = np.linspace(0.0, 1.0, SAMPLES)
    a = 2 * np.pi * turns * u
    a_w = a + (w.wob_a[:, None] * np.sin(w.wob_f[:, None] * a + w.wob_p[:, None])).sum(0)
    # the height wobble stays well inside the gap to the neighbouring turn of wire
    gap = (top - y0) / max(turns, 1e-6) / per_gap
    wob_y = w.wob_y * min(1.0, WOBBLE_SHARE * gap / w.wob_y.sum())
    y = y0 + (top - y0) * w.warp
    y = y + (wob_y[:, None] * np.sin(w.wob_f[:, None] * 1.7 * a + w.wob_p[:, None])).sum(0)
    depth = np.interp(a, w.knot_a, w.knot_depth)
    r = np.maximum(depth * cone_r(y), trunk_radius + 0.015)
    theta = phase + direction * a_w
    return np.stack([r * np.cos(theta), y, r * np.sin(theta)], axis=1)


def _length(p: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())


def _solve_turns(
    w: _Winding, target: float, y0: float, y1: float, max_gap: float, per_gap: int,
    direction: float, cone_r, trunk_radius: float,
) -> tuple[float, float]:
    """``(turns, top)`` for ``target`` metres of wire to fit the band ``y0``-``y1``. Wire
    too short to wind the band at least every ``max_gap`` metres only reaches ``top`` <
    ``y1``."""
    def path(turns: float, top: float) -> np.ndarray:
        return _path(w, turns, y0, top, per_gap, 0.0, direction, cone_r, trunk_radius)

    def min_turns(top: float) -> float:
        return max((top - y0) / max_gap, 0.25)

    if target <= 0:
        return min_turns(y1), y1
    if _length(path(min_turns(y1), y1)) > target:
        # Too short for the band: find the height it reaches at the loosest winding.
        lo, hi = y0, y1
        for _ in range(40):
            mid = (lo + hi) / 2
            if _length(path(min_turns(mid), mid)) > target:
                hi = mid
            else:
                lo = mid
        return min_turns(lo), lo
    lo, hi = min_turns(y1), max(min_turns(y1) * 2, 2.0)
    while _length(path(hi, y1)) < target:
        if hi >= MAX_TURNS:
            raise SpecError(
                f"{target:.0f} m of wire is more than fits on this tree (about "
                f"{_length(path(MAX_TURNS, y1)):.0f} m at most). Use fewer LEDs, a shorter "
                "strip or a bigger tree."
            )
        hi = min(hi * 2, MAX_TURNS)
    for _ in range(50):
        mid = (lo + hi) / 2
        if _length(path(mid, y1)) < target:
            lo = mid
        else:
            hi = mid
    return hi, y1


def _along(
    dense: np.ndarray, w: _Winding, turns: float, count: int, spacing: float, offset: float,
    phase: float, y0: float, top: float,
) -> tuple[np.ndarray, float, tuple[float, float]]:
    """LEDs every ``spacing`` along the winding ``dense`` from ``offset`` metres in,
    turned ``phase`` round the trunk, until the strip runs out. Returns the positions
    (bottom end first), the turns the strip makes, and the heights it starts and ends at
    (leaving out the wobble)."""
    seg = np.linalg.norm(np.diff(dense, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    s_led = np.minimum(offset + np.arange(count) * spacing, s[-1])
    pts = np.stack([np.interp(s_led, s, dense[:, i]) for i in range(3)], axis=1)
    c, sn = np.cos(phase), np.sin(phase)
    pts[:, 0], pts[:, 2] = pts[:, 0] * c - pts[:, 2] * sn, pts[:, 0] * sn + pts[:, 2] * c
    u = np.interp(s_led[[0, -1]], s, np.linspace(0.0, 1.0, len(s)))
    ya, yb = y0 + (top - y0) * np.interp(u, np.linspace(0, 1, len(w.warp)), w.warp)
    return pts, float(turns * (u[1] - u[0])), (float(ya), float(yb))


def _pick(value: float | None, random_value: float) -> float:
    return float(random_value if value is None else value)


def _int(v: Any, name: str) -> int:
    if isinstance(v, bool):
        raise SpecError(f"{name} must be a whole number")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if not isinstance(v, int):
        raise SpecError(f"{name} must be a whole number, got {v!r}")
    return v


def _opt_num(v: Any, name: str) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise SpecError(f"{name} must be a number, got {v!r}")
    return float(v)


def _in_range(v: float, key: str, name: str) -> None:
    lo, hi = LIMITS[key]
    if not lo <= v <= hi:
        raise SpecError(f"{name} must be {lo:g}-{hi:g}, got {v:g}")
