"""Position-aware 3D effects: they colour each LED by where it is on the tree.

They work in the map's normalised frame (y 0-1 up the tree, x and z centred on the
trunk at the same scale; see :class:`treemap.mapping.model.Geometry`), so sizes and
widths are fractions of the tree's height.
"""

from __future__ import annotations

import numpy as np

from treemap.effects.base import CHRISTMAS, MapEffect, Param, hsv_to_rgb
from treemap.effects.registry import register
from treemap.mapping.model import TreeMap

TAU = 2 * np.pi
AXES = {"up": (1, 1), "down": (1, -1), "left-right": (0, 1), "front-back": (2, -1)}


def _sweep(phase: float, bounce: bool) -> float:
    """0-1 position of a sweep after ``phase`` passes: a sawtooth, or a triangle."""
    if bounce:
        return 1 - abs(phase % 2 - 1)
    return phase % 1


class _Effect3D(MapEffect):
    group = "3D"


@register
class Plane(_Effect3D):
    name = "plane"
    label = "Plane"
    description = "A glowing plane sweeping through the tree, or turning round the trunk."
    params = (
        Param("direction", "choice", "up", choices=(*AXES, "around"),
              help="'around' turns a half-plane round the trunk like a lighthouse beam"),
        Param("color", "color", (255, 255, 255)),
        Param("background", "color", (0, 0, 0)),
        Param("speed", "float", 0.4, min=0.02, max=3, step=0.01,
              help="passes (or turns) per second"),
        Param("width", "float", 0.08, min=0.01, max=0.5, step=0.01,
              help="half-thickness, fraction of the tree height"),
        Param("bounce", "bool", False, help="go back and forth instead of starting over"),
        Param("rainbow", "bool", False, help="a new colour every pass"),
    )

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g, w = m.geometry, self.p["width"]
        phase = t * self.p["speed"]
        f = _sweep(phase, self.p["bounce"])
        if self.p["direction"] == "around":
            a = TAU * f
            x, z = g.xyz[:, 0], g.xyz[:, 2]
            across = x * np.cos(a) - z * np.sin(a)  # distance to the full plane
            along = x * np.sin(a) + z * np.cos(a)  # >= 0 on the beam's side of the trunk
            dist = np.where(along >= 0, np.abs(across), np.hypot(across, along))
        else:
            axis, sign = AXES[self.p["direction"]]
            lo, hi = g.lo[axis] - 2 * w, g.hi[axis] + 2 * w  # starts and ends off the tree
            level = lo + (f if sign > 0 else 1 - f) * (hi - lo)
            dist = np.abs(g.xyz[:, axis] - level)
        weight = np.clip(1 - dist / w, 0, 1)[:, None]
        color = hsv_to_rgb(np.floor(phase) * 0.17) if self.p["rainbow"] else self.color("color")
        return weight * color + (1 - weight) * self.color("background")


@register
class Rainbow3D(_Effect3D):
    name = "rainbow3d"
    label = "3D rainbow"
    description = "A rainbow flowing up the tree, round it, out from the trunk or on a tilt."
    params = (
        Param("direction", "choice", "up", choices=("up", "around", "out", "tilted"),
              help="'tilted' slants the bands and turns them slowly round the trunk"),
        Param("speed", "float", 0.2, min=-2, max=2, step=0.01, help="hue cycles per second"),
        Param("repeats", "float", 1.0, min=0.1, max=10, step=0.1,
              help="rainbows across the tree ('around' rounds it to whole ones)"),
        Param("saturation", "float", 1.0, min=0, max=1, step=0.01),
    )

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g, direction, repeats = m.geometry, self.p["direction"], self.p["repeats"]
        if direction == "up":
            s = g.h
        elif direction == "around":
            s = g.theta / TAU
            repeats = max(round(repeats), 1)  # whole rainbows, or there's a seam at the back
        elif direction == "out":
            s = g.r / max(float(g.r.max()), 1e-6)
        else:  # tilted 40° off vertical, the tilt turning round the trunk every 20 s
            a, tilt = TAU * t / 20, np.radians(40)
            side = g.xyz[:, 0] * np.sin(a) + g.xyz[:, 2] * np.cos(a)
            s = g.h * np.cos(tilt) + side * np.sin(tilt)
        return hsv_to_rgb(s * repeats - t * self.p["speed"], self.p["saturation"])


@register
class Spiral(_Effect3D):
    name = "spiral"
    label = "Spiral"
    description = "Helix lines winding up the tree and turning, or candy-cane stripes."
    params = (
        Param("style", "choice", "helix", choices=("helix", "candy"),
              help="helix: lines on black; candy: stripes of both colours"),
        Param("color", "color", (255, 0, 0)),
        Param("color2", "color", (255, 255, 255), label="Second colour", help="candy only"),
        Param("arms", "int", 2, min=1, max=8, step=1, help="helix lines or stripe pairs"),
        Param("turns", "float", 2.0, min=-8, max=8, step=0.1,
              help="how often each arm winds round the trunk, bottom to top"),
        Param("speed", "float", 0.25, min=-3, max=3, step=0.01,
              help="turns per second round the trunk"),
        Param("width", "float", 0.4, min=0.05, max=1, step=0.01,
              help="share of each arm's period that's lit (candy: in the first colour)"),
        Param("rainbow", "bool", False, help="helix: each arm its own, shifting colour"),
    )

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g, arms, width = m.geometry, self.p["arms"], self.p["width"]
        phase = arms * (g.theta / TAU + self.p["turns"] * g.h - self.p["speed"] * t)
        if self.p["style"] == "candy":
            first = (phase % 1 < width)[:, None]
            return np.where(first, self.color("color"), self.color("color2"))
        nearest = np.round(phase)  # the centre line of the closest arm
        level = np.clip(1 - np.abs(phase - nearest) / (width / 2), 0, 1)[:, None]
        if self.p["rainbow"]:
            return level * hsv_to_rgb((nearest % arms) / arms + 0.05 * t)
        return level * self.color("color")


@register
class Sphere(_Effect3D):
    name = "sphere"
    label = "Bursts"
    description = "Glowing spheres bursting out from random points on the tree."
    params = (
        Param("palette", "choice", "rainbow", choices=("rainbow", "christmas", "color")),
        Param("color", "color", (255, 255, 255), help="used by the 'color' palette"),
        Param("rate", "float", 1.2, min=0.1, max=10, step=0.1, help="bursts per second"),
        Param("speed", "float", 0.5, min=0.05, max=3, step=0.05,
              help="growth, tree heights per second"),
        Param("size", "float", 0.5, min=0.1, max=1.5, step=0.05,
              help="largest radius, fraction of the tree height"),
        Param("width", "float", 0.07, min=0.02, max=0.3, step=0.01,
              help="shell thickness, fraction of the tree height"),
    )

    def setup(self) -> None:
        super().setup()
        self.bursts: list[tuple[np.ndarray, float, np.ndarray]] = []  # centre, start, rgb
        self.next_burst = 0.0

    def _color(self) -> np.ndarray:
        pal = self.p["palette"]
        if pal == "rainbow":
            return hsv_to_rgb(np.array([self.rng.random()]))[0]
        if pal == "christmas":
            return CHRISTMAS[self.rng.integers(len(CHRISTMAS))]
        return self.color("color")

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g = m.geometry
        lifetime = (self.p["size"] + self.p["width"]) / self.p["speed"]
        self.next_burst = max(self.next_burst, t - lifetime)  # after a pause, don't flood
        valid = np.flatnonzero(g.valid)
        while self.next_burst <= t and len(valid):
            centre = g.xyz[self.rng.choice(valid)]
            self.bursts.append((centre, self.next_burst, self._color()))
            self.next_burst += self.rng.exponential(1 / self.p["rate"])
        self.bursts = [b for b in self.bursts if t - b[1] < lifetime]

        frame = self.blank()
        for centre, t0, rgb in self.bursts:
            radius = (t - t0) * self.p["speed"]
            dist = np.linalg.norm(g.xyz - centre, axis=1)
            shell = np.clip(1 - np.abs(dist - radius) / self.p["width"], 0, 1)
            fade = max(1 - radius / self.p["size"], 0.0)
            np.maximum(frame, (shell * fade)[:, None] * rgb, out=frame)
        return frame
