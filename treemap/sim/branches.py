"""The simulated tree's branches, for the virtual WLED's screen to cover in needles.

A fir grows in whorls: every 7-12 cm up the trunk a ring of 4-8 main branches. Low
branches stick out nearly level and sag in the middle; higher ones point more upwards.
Each main branch carries side branchlets, longest near the trunk, and the trunk carries
on above the last whorl as the leader. Every main branch tip sits on the tree's cone.

Lights are clipped onto branches, so an LED that would otherwise float between branches
gets a short twig from the nearest branch to it.

Branches come from their own random stream, seeded from the tree's seed, so they can be
rebuilt for tree files saved before branches existed (format version 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

MAIN, SIDE, TWIG = 0, 1, 2  # branch levels
WHORL_GAP = (0.07, 0.12)  # m between whorls at the bottom; they get closer near the top
TWIG_FROM = 0.03  # m: an LED further than this from every branch gets a twig


@dataclass
class Branch:
    level: int  # MAIN (or the leader), SIDE branchlet, or TWIG holding an LED
    points: np.ndarray  # (k, 3) m, from where it joins its parent out to its tip
    radius: tuple[float, float]  # wood radius at its base and tip, m

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "radius": [round(r, 4) for r in self.radius],
            "points": np.round(self.points, 4).tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Branch:
        r0, r1 = d["radius"]
        return cls(int(d["level"]), np.asarray(d["points"], dtype=np.float64), (float(r0), float(r1)))


def grow_branches(
    seed: int, height: float, radius: float, trunk_radius: float, leds: np.ndarray
) -> list[Branch]:
    """Branches for a tree of this size whose LEDs are at ``leds`` (N, 3)."""
    rng = np.random.default_rng([seed, 0xB4A])
    out: list[Branch] = []
    y = height * rng.uniform(0.03, 0.06)
    top = height * rng.uniform(0.86, 0.9)
    while y < top:
        t = y / height
        n = max(int(round(7 - 3 * t)) + int(rng.integers(-1, 2)), 3)
        base = rng.uniform(0, 2 * np.pi)
        for j in range(n):
            a = base + (j + rng.uniform(-0.3, 0.3)) * 2 * np.pi / n
            out += _main_branch(rng, y + rng.uniform(-0.012, 0.012), a, height, radius,
                                trunk_radius)
        y += rng.uniform(*WHORL_GAP) * (1 - 0.4 * t)
    lean = rng.uniform(-0.01, 0.01, 2)
    leader = np.array([[0, y - 0.05, 0], [lean[0] / 2, (y + height) / 2, lean[1] / 2],
                       [lean[0], height, lean[1]]])
    out.append(Branch(MAIN, leader, (_trunk_r(trunk_radius, y, height), 0.002)))
    out += _twigs(out, leds)
    return out


def _trunk_r(trunk_radius: float, y: float, height: float) -> float:
    return trunk_radius * max(1 - 0.9 * y / height, 0.1)


def _main_branch(
    rng: np.random.Generator, y: float, a: float, height: float, radius: float,
    trunk_radius: float,
) -> list[Branch]:
    t = y / height
    tan = np.tan(np.radians(-4 + 36 * t + rng.uniform(-6, 6)))  # low level, high upwards
    # how far out the tip reaches, so it lands on the cone (at the tip's own height)
    reach = radius * (1 - t) / (1 + radius * max(tan, 0.0) / height) * rng.uniform(0.85, 1.02)
    r0 = _trunk_r(trunk_radius, y, height)
    reach = max(reach, r0 + 0.03)
    sag = rng.uniform(0.03, 0.09)

    s = np.linspace(0, 1, 6)
    h = r0 + s * (reach - r0)  # distance from the trunk
    theta = a + np.concatenate([[0], np.cumsum(rng.normal(0, 0.04, 5))])
    rise = y + s * reach * tan - sag * reach * np.sin(np.pi * s)
    pts = np.stack([h * np.cos(theta), rise, h * np.sin(theta)], axis=1)
    out = [Branch(MAIN, pts, (float(min(0.004 + 0.012 * reach, 0.012)), 0.0015))]

    # side branchlets, alternating left and right, shorter towards the tip
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    along = np.concatenate([[0], np.cumsum(seg)])
    side = 1.0 if rng.random() < 0.5 else -1.0
    d = along[-1] * 0.12
    while d < along[-1] - 0.02:
        p = np.array([np.interp(d, along, pts[:, i]) for i in range(3)])
        k = min(np.searchsorted(along, d, side="right") - 1, len(seg) - 1)
        fwd = (pts[k + 1] - pts[k]) / seg[k]
        ang = side * rng.uniform(0.6, 1.0)
        c, sn = np.cos(ang), np.sin(ang)
        direction = np.array([fwd[0] * c - fwd[2] * sn, rng.uniform(-0.1, 0.3),
                              fwd[0] * sn + fwd[2] * c])
        direction /= np.linalg.norm(direction)
        length = min((0.3 * (along[-1] - d) + 0.04) * rng.uniform(0.7, 1.1), 0.2)
        tip = p + direction * length
        mid = (p + tip) / 2 - [0, 0.12 * length, 0]  # droops a little
        out.append(Branch(SIDE, np.stack([p, mid, tip]), (0.003, 0.001)))
        side = -side
        d += rng.uniform(0.045, 0.075)
    return out


def _twigs(branches: list[Branch], leds: np.ndarray) -> list[Branch]:
    """A twig from the nearest branch to every LED further than TWIG_FROM from one."""
    a = np.concatenate([b.points[:-1] for b in branches])
    ab = np.concatenate([np.diff(b.points, axis=0) for b in branches])
    ab2 = np.maximum((ab * ab).sum(1), 1e-12)
    twigs = []
    for chunk in np.array_split(leds, max(len(leds) // 64, 1)):
        ap = chunk[:, None, :] - a[None]
        u = np.clip((ap * ab[None]).sum(2) / ab2, 0, 1)
        near = a[None] + u[..., None] * ab[None]
        dist = np.linalg.norm(chunk[:, None, :] - near, axis=2)
        best = dist.argmin(1)
        for p, k, q in zip(chunk, best, near[np.arange(len(chunk)), best]):
            gap = np.linalg.norm(p - q)
            if gap > TWIG_FROM:
                mid = (p + q) / 2 - [0, 0.15 * gap, 0]
                twigs.append(Branch(TWIG, np.stack([q, mid, p]), (0.0018, 0.0012)))
    return twigs
