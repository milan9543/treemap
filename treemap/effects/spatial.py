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

# Colour gradients, dark to bright, for effects that map a 0-1 value to a colour.
GRADIENTS = {
    "lava": [(0, 0, 0), (120, 0, 0), (255, 60, 0), (255, 170, 0), (255, 240, 120)],
    "ocean": [(0, 0, 30), (0, 40, 160), (0, 140, 255), (60, 220, 255), (210, 255, 255)],
    "forest": [(0, 15, 0), (0, 90, 10), (40, 180, 20), (170, 220, 40), (255, 200, 60)],
}


def gradient(name: str, s: np.ndarray) -> np.ndarray:
    """Colours 0-255 along a gradient for values ``s`` 0-1 (clipped): ``s.shape + (3,)``."""
    stops = np.asarray(GRADIENTS[name], dtype=np.float32)
    x = np.linspace(0, 1, len(stops))
    s = np.clip(s, 0, 1)
    return np.stack([np.interp(s, x, stops[:, c]) for c in range(3)], axis=-1).astype(np.float32)


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


@register
class Ripple(_Effect3D):
    name = "ripple"
    label = "Ripples"
    description = "Rings of light spreading through the tree from the top, middle or bottom."
    params = (
        Param("origin", "choice", "top", choices=("top", "middle", "bottom")),
        Param("color", "color", (80, 160, 255)),
        Param("rainbow", "bool", False, help="every ring its own colour"),
        Param("speed", "float", 0.8, min=-3, max=3, step=0.05,
              help="rings per second (negative: they run inwards)"),
        Param("spacing", "float", 0.3, min=0.05, max=1, step=0.01,
              help="distance between rings, fraction of the tree height"),
        Param("sharpness", "float", 6, min=1, max=30, step=0.5, help="higher: thinner rings"),
    )

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g = m.geometry
        y = {"top": g.hi[1], "middle": (g.lo[1] + g.hi[1]) / 2, "bottom": g.lo[1]}[self.p["origin"]]
        dist = np.linalg.norm(g.xyz - np.array([0, y, 0], np.float32), axis=1)
        phase = dist / self.p["spacing"] - t * self.p["speed"]
        level = ((1 + np.cos(TAU * phase)) / 2) ** self.p["sharpness"]
        if self.p["rainbow"]:
            return level[:, None] * hsv_to_rgb(np.round(phase) * 0.13)
        return level[:, None] * self.color("color")


@register
class Plasma(_Effect3D):
    name = "plasma"
    label = "Plasma"
    description = "Slowly flowing blobs of colour drifting through the tree in 3D."
    params = (
        Param("palette", "choice", "lava", choices=("lava", "ocean", "forest", "rainbow")),
        Param("speed", "float", 1.0, min=0.05, max=5, step=0.05),
        Param("scale", "float", 0.5, min=0.1, max=2, step=0.05,
              help="blob size, fraction of the tree height"),
    )

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g, k, sp = m.geometry, 1 / self.p["scale"], self.p["speed"] * t
        x, y, z = g.xyz.T
        v = (np.sin(TAU * (x * k + sp * 0.11))
             + np.sin(TAU * (y * k * 0.8 - sp * 0.07))
             + np.sin(TAU * ((x + z) * k * 0.6 + sp * 0.13))
             + np.sin(TAU * (g.r * k * 1.3 - y * k * 0.4 - sp * 0.09)))
        s = (v / 4 + 1) / 2  # 0-1
        if self.p["palette"] == "rainbow":
            return hsv_to_rgb(s + sp * 0.02)
        return gradient(self.p["palette"], s * 1.15 - 0.1)  # some LEDs reach black and white


@register
class Radar(_Effect3D):
    name = "radar"
    label = "Radar"
    description = "A beam turning round the trunk, leaving a fading afterglow behind it."
    params = (
        Param("color", "color", (0, 255, 90)),
        Param("background", "color", (0, 0, 0)),
        Param("speed", "float", 0.4, min=-3, max=3, step=0.01,
              help="turns per second (negative: the other way)"),
        Param("trail", "float", 0.3, min=0.02, max=1, step=0.01,
              help="afterglow length, fraction of a turn"),
    )

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        speed = self.p["speed"]
        beam = t * speed  # turns
        behind = (beam - m.geometry.theta / TAU) % 1.0  # turns since the beam passed
        if speed < 0:
            behind = 1.0 - behind
        level = np.exp(-behind / (self.p["trail"] / 3))[:, None]
        return level * self.color("color") + (1 - level) * self.color("background")


@register
class Fireflies(_Effect3D):
    name = "fireflies"
    label = "Fireflies"
    description = "Little glowing lights drifting about inside the tree, blinking."
    params = (
        Param("color", "color", (190, 255, 40)),
        Param("count", "int", 8, min=1, max=40, step=1),
        Param("size", "float", 0.06, min=0.02, max=0.25, step=0.01,
              help="glow radius, fraction of the tree height"),
        Param("speed", "float", 1.0, min=0.1, max=4, step=0.05),
        Param("blink", "bool", True),
    )

    def setup(self) -> None:
        super().setup()
        k = 40  # the most fireflies; each one's own random flight path
        self.orbit = self.rng.uniform(0.04, 0.15, k) * self.rng.choice([-1, 1], k)  # turns/s
        self.theta0 = self.rng.uniform(0, TAU, k)
        self.bob = self.rng.uniform(0.03, 0.09, k)  # height oscillations/s
        self.phase = self.rng.uniform(0, TAU, (3, k))
        self.depth = self.rng.uniform(0.75, 1.0, k)  # how far out: near the LEDs on the outside
        self.blink_rate = self.rng.uniform(0.2, 0.5, k)  # blinks per second

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g, n, st = m.geometry, self.p["count"], t * self.p["speed"]
        lo, hi = g.lo[1], g.hi[1]
        h = lo + (hi - lo) * (0.5 + 0.42 * np.sin(TAU * self.bob[:n] * st + self.phase[0, :n]))
        # the tree's outline: how far out the LEDs reach at each height
        cone = np.percentile(g.r[g.valid] / np.maximum(1.03 * hi - g.h[g.valid], 0.05), 90)
        r = cone * np.maximum(1.03 * hi - h, 0.0) * self.depth[:n] * (
            0.85 + 0.15 * np.sin(TAU * 0.13 * st + self.phase[1, :n]))
        a = self.theta0[:n] + TAU * self.orbit[:n] * st
        pos = np.stack([r * np.sin(a), h, r * np.cos(a)], axis=1)  # (n, 3); θ = 0 at +z
        d2 = ((g.xyz[None, :, :] - pos[:, None, :]) ** 2).sum(axis=2)  # (fireflies, LEDs)
        glow = np.exp(-d2 / (2 * self.p["size"] ** 2))
        if self.p["blink"]:
            pulse = np.sin(TAU * self.blink_rate[:n] * t + self.phase[2, :n])
            glow = glow * np.clip(0.3 + pulse, 0, 1)[:, None]  # on ~60% of the time
        return np.clip(glow.sum(axis=0), 0, 1)[:, None] * self.color("color")


@register
class Fill(_Effect3D):
    name = "fill"
    label = "Fill up"
    description = "The tree fills with colour from the bottom like a glass, a new colour each time."
    params = (
        Param("palette", "choice", "christmas", choices=("christmas", "rainbow")),
        Param("seconds", "float", 4.0, min=0.5, max=30, step=0.5, help="seconds per fill"),
        Param("wave", "float", 0.05, min=0, max=0.25, step=0.01,
              help="how much the surface sloshes, fraction of the tree height"),
    )

    def _color(self, k: int) -> np.ndarray:
        if self.p["palette"] == "rainbow":
            return hsv_to_rgb(np.array([k * 0.17]))[0]
        return CHRISTMAS[k % len(CHRISTMAS)]

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g, wave = m.geometry, self.p["wave"]
        k, f = divmod(t / self.p["seconds"], 1.0)
        k = int(k)
        lo, hi = g.lo[1] - 2 * wave - 0.03, g.hi[1] + 2 * wave + 0.03
        surface = lo + f * (hi - lo) + wave * np.sin(2 * g.theta + TAU * 0.7 * t) * np.sin(TAU * 0.3 * t)
        below = np.clip((surface - g.h) / 0.03 + 0.5, 0, 1)[:, None]  # soft edge
        return below * self._color(k) + (1 - below) * self._color(k - 1)


@register
class Blocks(_Effect3D):
    name = "blocks"
    label = "3D checkerboard"
    description = "The tree cut into cubes of two colours, the whole pattern turning round the trunk."
    params = (
        Param("color", "color", (255, 0, 0)),
        Param("color2", "color", (0, 140, 0), label="Second colour"),
        Param("size", "float", 0.2, min=0.05, max=0.6, step=0.01,
              help="cube size, fraction of the tree height"),
        Param("speed", "float", 0.05, min=-1, max=1, step=0.01, help="turns per second"),
    )

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g, size = m.geometry, self.p["size"]
        a = TAU * self.p["speed"] * t
        x, y, z = g.xyz.T
        xr, zr = x * np.cos(a) - z * np.sin(a), x * np.sin(a) + z * np.cos(a)
        cells = np.floor(xr / size) + np.floor(y / size) + np.floor(zr / size)
        first = (cells.astype(int) % 2 == 0)[:, None]
        return np.where(first, self.color("color"), self.color("color2"))
