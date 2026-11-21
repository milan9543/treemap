"""Position-aware 3D effects: they colour each LED by where it is on the tree.

They work in the map's normalised frame (y 0-1 up the tree, x and z centred on the
trunk at the same scale; see :class:`treemap.mapping.model.Geometry`), so sizes and
widths are fractions of the tree's height.

They all keep to Christmas colours: every colour setting picks one of :data:`XMAS`, and
effects that used to run through the rainbow cycle through Christmas colours instead.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from treemap.effects.base import MapEffect, Param
from treemap.effects.registry import register
from treemap.mapping.model import TreeMap

TAU = 2 * np.pi
AXES = {"up": (1, 1), "down": (1, -1), "left-right": (0, 1), "front-back": (2, -1)}

# The Christmas colours every 3D effect draws from.
XMAS = {
    "red": (255, 0, 0),
    "green": (0, 190, 20),
    "gold": (255, 140, 0),
    "warm white": (255, 150, 60),
    "white": (255, 255, 255),
}
COLORS = tuple(XMAS)
CYCLE = np.array([XMAS[k] for k in ("red", "green", "gold", "white")], dtype=np.float32)

# Looping palettes for colour that flows (bands, every new pass or ring).
PALETTES = {
    "christmas": ["red", "gold", "green", "white"],
    "candy cane": ["red", "white"],
    "red & green": ["red", "green"],
    "green & gold": ["green", "gold"],
    "gold": ["gold", "warm white"],
}

# Gradients, dark to bright, for effects that map a 0-1 value to a colour.
GRADIENTS = {
    "christmas": [(60, 0, 0), (255, 0, 0), (255, 140, 0), (0, 190, 20), (0, 50, 5)],
    "candlelight": [(0, 0, 0), (120, 0, 0), (255, 40, 0), (255, 140, 0), (255, 200, 120)],
    "fir": [(0, 10, 0), (0, 80, 10), (0, 190, 20), (220, 150, 0), (255, 190, 90)],
    "candy cane": [(60, 0, 0), (255, 0, 0), (255, 80, 80), (255, 255, 255)],
}


def xmas(name: str) -> np.ndarray:
    return np.asarray(XMAS[name], dtype=np.float32)


def cycle(k: np.ndarray | float | int) -> np.ndarray:
    """The ``k``-th Christmas colour, going round red, green, gold, white."""
    return CYCLE[np.asarray(k, dtype=np.int64) % len(CYCLE)]


def palette(name: str, s: np.ndarray) -> np.ndarray:
    """Colours 0-255 round a looping palette for ``s`` (one loop per 1): ``s.shape + (3,)``."""
    stops = np.asarray([XMAS[k] for k in PALETTES[name]], dtype=np.float32)
    stops = np.concatenate([stops, stops[:1]])
    x = np.linspace(0, 1, len(stops))
    s = np.mod(s, 1.0)
    return np.stack([np.interp(s, x, stops[:, c]) for c in range(3)], axis=-1).astype(np.float32)


def palette_color(name: str, k: int) -> np.ndarray:
    """The ``k``-th colour of a palette, going round it."""
    names = PALETTES[name]
    return xmas(names[k % len(names)])


def gradient(name: str, s: np.ndarray) -> np.ndarray:
    """Colours 0-255 along a named gradient for values ``s`` 0-1 (clipped):
    ``s.shape + (3,)``."""
    return gradient_stops(GRADIENTS[name], s)


def gradient_stops(stops: list[tuple[int, int, int]], s: np.ndarray) -> np.ndarray:
    """Colours 0-255 along the given gradient stops for values ``s`` 0-1 (clipped)."""
    stops_a = np.asarray(stops, dtype=np.float32)
    x = np.linspace(0, 1, len(stops_a))
    s = np.clip(s, 0, 1)
    return np.stack([np.interp(s, x, stops_a[:, c]) for c in range(3)], axis=-1).astype(np.float32)


def _color_param(name: str, default: str, **kw) -> Param:
    return Param(name, "choice", default, choices=COLORS, **kw)


def _background_params() -> tuple[Param, Param]:
    """The colour of the LEDs the animation isn't lighting, and how bright it is."""
    return (
        Param("background", "choice", "off", choices=("off", *COLORS),
              help="colour of the LEDs the animation isn't lighting"),
        Param("background_level", "float", 0.4, min=0.05, max=1, step=0.05,
              label="Background brightness"),
    )


def _sweep(phase: float, bounce: bool) -> float:
    """0-1 position of a sweep after ``phase`` passes: a sawtooth, or a triangle."""
    if bounce:
        return 1 - abs(phase % 2 - 1)
    return phase % 1


def _fill_params(wave: float, wave_help: str) -> tuple[Param, ...]:
    return (
        Param("palette", "choice", "christmas", choices=tuple(PALETTES),
              help="the colours the fills go through, in turn"),
        Param("speed", "float", 0.25, min=0.03, max=2, step=0.01, label="Animation speed",
              help="fills per second: 0.25 takes 4 s to fill the tree"),
        Param("hold", "float", 1.0, min=0, max=30, step=0.5, label="Seconds still",
              help="how long the tree stays one colour before the next fill"),
        Param("wave", "float", wave, min=0, max=0.25, step=0.01, help=wave_help),
    )


class _Effect3D(MapEffect):
    group = "3D"

    def fill_phase(self, t: float) -> tuple[int, float]:
        """For the fill effects: which fill is running (k) and how far it's got (0-1;
        it stays at 1 while the tree holds still)."""
        fill_s = 1 / self.p["speed"]
        k, into = divmod(t, fill_s + self.p["hold"])
        return int(k), min(into / fill_s, 1.0)

    def fill_colors(self, k: int) -> tuple[np.ndarray, np.ndarray]:
        """The colour fill ``k`` brings, and the one it covers."""
        return palette_color(self.p["palette"], k), palette_color(self.p["palette"], k - 1)

    def background(self) -> np.ndarray:
        name = self.p["background"]
        return np.zeros(3, np.float32) if name == "off" else xmas(name) * self.p["background_level"]

    def over_background(self, level: np.ndarray, color: np.ndarray) -> np.ndarray:
        """``color`` at ``level`` (per LED, 0-1) over the background."""
        level = np.asarray(level, np.float32).reshape(-1, 1)
        return level * color + (1 - level) * self.background()


@register
class Plane(_Effect3D):
    name = "plane"
    label = "Plane"
    description = "A glowing plane sweeping through the tree, or turning round the trunk."
    params = (
        Param("direction", "choice", "up", choices=(*AXES, "around"),
              help="'around' turns a half-plane round the trunk like a lighthouse beam"),
        _color_param("color", "gold"),
        *_background_params(),
        Param("speed", "float", 0.4, min=0.02, max=3, step=0.01,
              help="passes (or turns) per second"),
        Param("width", "float", 0.08, min=0.01, max=0.5, step=0.01,
              help="half-thickness, fraction of the tree height"),
        Param("bounce", "bool", False, help="go back and forth instead of starting over"),
        Param("cycle", "bool", False, help="a new Christmas colour every pass"),
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
        color = cycle(np.floor(phase)) if self.p["cycle"] else xmas(self.p["color"])
        return self.over_background(np.clip(1 - dist / w, 0, 1), color)


@register
class Rainbow3D(_Effect3D):
    name = "rainbow3d"
    label = "3D colour bands"
    description = "Bands of Christmas colours flowing up the tree, round it, out from the trunk or on a tilt."
    params = (
        Param("direction", "choice", "up", choices=("up", "around", "out", "tilted"),
              help="'tilted' slants the bands and turns them slowly round the trunk"),
        Param("palette", "choice", "christmas", choices=tuple(PALETTES)),
        Param("speed", "float", 0.2, min=-2, max=2, step=0.01,
              help="times round the palette per second"),
        Param("repeats", "float", 1.0, min=0.1, max=10, step=0.1,
              help="times round the palette across the tree ('around' rounds it to whole ones)"),
    )

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g, direction, repeats = m.geometry, self.p["direction"], self.p["repeats"]
        if direction == "up":
            s = g.h
        elif direction == "around":
            s = g.theta / TAU
            repeats = max(round(repeats), 1)  # whole loops, or there's a seam at the back
        elif direction == "out":
            s = g.r / max(float(g.r.max()), 1e-6)
        else:  # tilted 40° off vertical, the tilt turning round the trunk every 20 s
            a, tilt = TAU * t / 20, np.radians(40)
            side = g.xyz[:, 0] * np.sin(a) + g.xyz[:, 2] * np.cos(a)
            s = g.h * np.cos(tilt) + side * np.sin(tilt)
        return palette(self.p["palette"], s * repeats - t * self.p["speed"])


@register
class Spiral(_Effect3D):
    name = "spiral"
    label = "Spiral"
    description = "Helix lines winding up the tree and turning, or candy-cane stripes."
    params = (
        Param("style", "choice", "helix", choices=("helix", "candy"),
              help="helix: lines on black; candy: stripes of both colours"),
        _color_param("color", "red"),
        _color_param("color2", "white", label="Second colour", help="candy only"),
        Param("arms", "int", 2, min=1, max=8, step=1, help="helix lines or stripe pairs"),
        Param("turns", "float", 2.0, min=-8, max=8, step=0.1,
              help="how often each arm winds round the trunk, bottom to top"),
        Param("speed", "float", 0.25, min=-3, max=3, step=0.01,
              help="turns per second round the trunk"),
        Param("width", "float", 0.4, min=0.05, max=1, step=0.01,
              help="share of each arm's period that's lit (candy: in the first colour)"),
        Param("mixed", "bool", False, help="helix: each arm its own Christmas colour"),
        *_background_params(),
    )

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g, arms, width = m.geometry, self.p["arms"], self.p["width"]
        phase = arms * (g.theta / TAU + self.p["turns"] * g.h - self.p["speed"] * t)
        if self.p["style"] == "candy":
            first = (phase % 1 < width)[:, None]
            return np.where(first, xmas(self.p["color"]), xmas(self.p["color2"]))
        nearest = np.round(phase)  # the centre line of the closest arm
        level = np.clip(1 - np.abs(phase - nearest) / (width / 2), 0, 1)
        color = cycle(nearest % arms) if self.p["mixed"] else xmas(self.p["color"])
        return self.over_background(level, color)


@dataclass
class _Burst:
    centre: np.ndarray  # (3,)
    t0: float
    rgb: np.ndarray  # (3,)
    dirs: np.ndarray  # (sparks, 3) unit vectors
    reach: np.ndarray  # (sparks,) how far each spark flies, as a share of `size`
    crackle: np.ndarray  # (sparks,) twinkle frequency, Hz


SPARK_GLOW = 0.05  # spark glow radius (sigma), fraction of the tree height
CLOUD = 0.35  # brightness of the colour cloud the sparks leave behind them
SPARK_DRAG_S = 0.16  # sparks shoot out and slow down with this time constant
FLASH_S = 0.25  # how long the white flash at the centre lasts


@register
class Sphere(_Effect3D):
    name = "sphere"
    label = "Bursts"
    description = ("Firework explosions: a white flash and a spray of sparks flying out, "
                   "cooling to their colour, falling and crackling as they fade.")
    params = (
        Param("style", "choice", "explosion", choices=("explosion", "ring"),
              help="explosion: sparks flying out; ring: a shell of light growing and fading"),
        Param("palette", "choice", "christmas", choices=("christmas", "one colour")),
        _color_param("color", "gold", help="used by 'one colour'"),
        Param("rate", "float", 0.7, min=0.1, max=10, step=0.1, help="bursts per second"),
        Param("size", "float", 0.3, min=0.05, max=1.5, step=0.05,
              help="how far the sparks fly (ring: largest radius), fraction of the tree height"),
        Param("sparks", "int", 60, min=8, max=150, step=1, help="explosion: sparks per burst"),
        Param("fade", "float", 1.6, min=0.3, max=6, step=0.1, label="Fade (s)",
              help="explosion: how long the sparks glow"),
        Param("gravity", "float", 0.35, min=0, max=1, step=0.05,
              help="explosion: how much the sparks fall as they fade"),
        Param("crackle", "bool", True,
              help="explosion: sparks twinkle as they burn out; off: they fade smoothly"),
        Param("speed", "float", 0.6, min=0.05, max=3, step=0.05,
              help="ring: growth, tree heights per second"),
        Param("width", "float", 0.07, min=0.02, max=0.3, step=0.01,
              help="ring: shell thickness, fraction of the tree height"),
        *_background_params(),
    )

    def setup(self) -> None:
        super().setup()
        self.bursts: list[_Burst] = []
        self.next_burst = 0.0

    def _color(self) -> np.ndarray:
        if self.p["palette"] == "christmas":
            return cycle(self.rng.integers(len(CYCLE)))
        return xmas(self.p["color"])

    def _lifetime(self) -> float:
        p = self.p
        if p["style"] == "ring":
            return (p["size"] + p["width"]) / p["speed"]
        return p["fade"]

    def _spawn(self, centre: np.ndarray, t0: float) -> _Burst:
        k = self.p["sparks"]
        dirs = self.rng.normal(size=(k, 3))
        dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
        return _Burst(centre, t0, self._color(), dirs, self.rng.uniform(0.55, 1.0, k),
                      self.rng.uniform(6.0, 14.0, k))

    def _ring(self, xyz: np.ndarray, b: _Burst, age: float) -> tuple[np.ndarray, np.ndarray]:
        p = self.p
        radius = age * p["speed"]
        dist = np.linalg.norm(xyz - b.centre, axis=1)
        level = np.clip(1 - np.abs(dist - radius) / p["width"], 0, 1)
        return level * max(1 - radius / p["size"], 0.0), b.rgb

    def _explosion(self, xyz: np.ndarray, b: _Burst, age: float) -> tuple[np.ndarray, np.ndarray]:
        p = self.p
        life = age / p["fade"]
        # sparks: where each one is now and a moment ago (its trail)
        ages = np.maximum(age - np.array([0.0, 0.03, 0.06, 0.09]), 0.0)
        out = 1 - np.exp(-ages / SPARK_DRAG_S)  # shoot out fast, then slow right down
        pts = b.centre + out[:, None, None] * (b.dirs * (b.reach * p["size"])[:, None])[None]
        pts[..., 1] -= (p["gravity"] * 0.25 * ages**2)[:, None]  # falling as they slow
        glow = (1 - life) ** 1.5 * np.array([1.0, 0.6, 0.35, 0.18])[:, None]  # trail dims
        if p["crackle"] and life > 0.45:  # crackle: twinkling unevenly as they burn out
            glow = glow * (0.55 + 0.45 * np.sin(TAU * b.crackle * age))[None]
        d2 = ((xyz[:, None, None, :] - pts[None]) ** 2).sum(axis=3)  # (N, trail, sparks)
        level = (np.exp(-d2 / (2 * SPARK_GLOW**2)) * glow[None]).max(axis=(1, 2))
        # a cloud of the burst's colour, filling the space the sparks have swept through
        dist = np.linalg.norm(xyz - b.centre, axis=1)
        front = out[0] * p["size"] * 0.8
        cloud = np.clip((front - dist) / 0.06 + 0.5, 0, 1) * CLOUD * (1 - life) ** 2
        level = np.maximum(level, cloud)
        # the flash: a white ball at the centre for the first moment
        flash = min(1.5 * max(1 - age / FLASH_S, 0.0), 1.0)
        if flash:
            sigma = 0.04 + 0.5 * min(age, 0.08)
            d2c = ((xyz - b.centre) ** 2).sum(axis=1)
            level = np.maximum(level, flash * np.exp(-d2c / (2 * sigma**2)))
        hot = max(1 - age / 0.35, 0.0)  # sparks start white-hot and cool to their colour
        return level, hot * np.array([255.0, 255, 255], np.float32) + (1 - hot) * b.rgb

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g = m.geometry
        lifetime = self._lifetime()
        self.next_burst = max(self.next_burst, t - lifetime)  # after a pause, don't flood
        valid = np.flatnonzero(g.valid)
        while self.next_burst <= t and len(valid):
            self.bursts.append(self._spawn(g.xyz[self.rng.choice(valid)], self.next_burst))
            self.next_burst += self.rng.exponential(1 / self.p["rate"])
        self.bursts = [b for b in self.bursts if t - b.t0 < lifetime]

        # each burst covers the ones before it (and the background) where it's lit
        frame = np.broadcast_to(self.background(), (self.n, 3)).astype(np.float32)
        draw = self._ring if self.p["style"] == "ring" else self._explosion
        for b in self.bursts:
            level, rgb = draw(g.xyz, b, t - b.t0)
            level = np.clip(level, 0, 1)[:, None]
            frame = frame * (1 - level) + level * rgb
        return frame


@register
class Ripple(_Effect3D):
    name = "ripple"
    label = "Ripples"
    description = "Rings of light spreading through the tree from the top, middle or bottom."
    params = (
        Param("origin", "choice", "top", choices=("top", "middle", "bottom")),
        _color_param("color", "gold"),
        Param("mixed", "bool", False, help="every ring its own Christmas colour"),
        Param("speed", "float", 0.8, min=-3, max=3, step=0.05,
              help="rings per second (negative: they run inwards)"),
        Param("spacing", "float", 0.3, min=0.05, max=1, step=0.01,
              help="distance between rings, fraction of the tree height"),
        Param("sharpness", "float", 6, min=1, max=30, step=0.5, help="higher: thinner rings"),
        *_background_params(),
    )

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g = m.geometry
        y = {"top": g.hi[1], "middle": (g.lo[1] + g.hi[1]) / 2, "bottom": g.lo[1]}[self.p["origin"]]
        dist = np.linalg.norm(g.xyz - np.array([0, y, 0], np.float32), axis=1)
        phase = dist / self.p["spacing"] - t * self.p["speed"]
        level = ((1 + np.cos(TAU * phase)) / 2) ** self.p["sharpness"]
        color = cycle(np.round(phase)) if self.p["mixed"] else xmas(self.p["color"])
        return self.over_background(level, color)


@register
class Plasma(_Effect3D):
    name = "plasma"
    label = "Plasma"
    description = "Slowly flowing blobs of colour drifting through the tree in 3D."
    params = (
        Param("palette", "choice", "christmas", choices=tuple(GRADIENTS)),
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
        return gradient(self.p["palette"], s * 1.15 - 0.1)  # some LEDs reach black and white


@register
class Radar(_Effect3D):
    name = "radar"
    label = "Radar"
    description = "A beam turning round the trunk, leaving a fading afterglow behind it."
    params = (
        _color_param("color", "green"),
        *_background_params(),
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
        level = np.exp(-behind / (self.p["trail"] / 3))
        return self.over_background(level, xmas(self.p["color"]))


@register
class Fireflies(_Effect3D):
    name = "fireflies"
    label = "Fireflies"
    description = "Little glowing lights drifting about inside the tree, blinking."
    params = (
        _color_param("color", "gold"),
        Param("count", "int", 8, min=1, max=40, step=1),
        Param("size", "float", 0.06, min=0.02, max=0.25, step=0.01,
              help="glow radius, fraction of the tree height"),
        Param("speed", "float", 1.0, min=0.1, max=4, step=0.05),
        Param("blink", "bool", True),
        *_background_params(),
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
        return self.over_background(np.clip(glow.sum(axis=0), 0, 1), xmas(self.p["color"]))


@register
class Fill(_Effect3D):
    name = "fill"
    label = "Fill up"
    description = "The tree fills with colour from the bottom like a glass, a new colour each time."
    params = _fill_params(0.05, "how much the surface sloshes, fraction of the tree height")

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g, wave = m.geometry, self.p["wave"]
        k, f = self.fill_phase(t)
        lo, hi = g.lo[1] - 2 * wave - 0.03, g.hi[1] + 2 * wave + 0.03
        surface = lo + f * (hi - lo) + wave * np.sin(2 * g.theta + TAU * 0.7 * t) * np.sin(TAU * 0.3 * t)
        below = np.clip((surface - g.h) / 0.03 + 0.5, 0, 1)[:, None]  # soft edge
        new, old = self.fill_colors(k)
        return below * new + (1 - below) * old


@register
class FillOut(_Effect3D):
    name = "fillout"
    label = "Fill outwards"
    description = ("The tree fills with colour outwards from its middle (or the top, bottom "
                   "or trunk), a new colour each time.")
    params = (
        Param("origin", "choice", "middle", choices=("middle", "top", "bottom", "trunk"),
              help="where the colour starts; 'trunk' spreads sideways, filling each "
                   "height from the inside out"),
        *_fill_params(0.04, "how much the edge wobbles, fraction of the tree height"),
    )

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g, wave, origin = m.geometry, self.p["wave"], self.p["origin"]
        k, f = self.fill_phase(t)
        if origin == "trunk":
            dist = g.r
        else:
            y = {"top": g.hi[1], "middle": (g.lo[1] + g.hi[1]) / 2, "bottom": g.lo[1]}[origin]
            dist = np.linalg.norm(g.xyz - np.array([0, y, 0], np.float32), axis=1)
        reach = float(dist[g.valid].max()) if g.valid.any() else 1.0
        lo, hi = -2 * wave - 0.03, reach + 2 * wave + 0.03  # starts and ends off the tree
        edge = lo + f * (hi - lo) + wave * np.sin(3 * g.theta + 5 * g.h + TAU * 0.6 * t) \
            * np.sin(TAU * 0.35 * t)
        inside = np.clip((edge - dist) / 0.03 + 0.5, 0, 1)[:, None]  # soft edge
        new, old = self.fill_colors(k)
        return inside * new + (1 - inside) * old


FIRE = [(0, 0, 0), (110, 0, 0), (230, 30, 0), (255, 110, 0), (255, 180, 30), (255, 230, 150)]
TONGUES = 7  # flame tongues round the trunk
PUFFS = 10  # blobs of flame breaking off the tips
SPARKS = 24


@register
class Fire(_Effect3D):
    name = "fire"
    label = "Campfire"
    description = ("A campfire at the foot of the tree: glowing coals, flickering tongues of "
                   "flame, puffs breaking off the tips and sparks flying up.")
    params = (
        Param("height", "float", 0.5, min=0.15, max=1.0, step=0.05,
              help="how high the tallest flames reach, fraction of the tree height"),
        Param("speed", "float", 1.0, min=0.2, max=3, step=0.05, help="how lively the fire is"),
        Param("sparks", "int", 8, min=0, max=SPARKS, step=1, help="sparks flying up at once"),
    )

    def setup(self) -> None:
        super().setup()
        r = self.rng
        self.coal_f = r.uniform(0.3, 1.2, self.n)  # each LED's own slow glow, as a coal
        self.coal_p = r.uniform(0, TAU, self.n)
        self.tongue_theta = (np.arange(TONGUES) + r.uniform(-0.3, 0.3, TONGUES)) * TAU / TONGUES
        self.tongue_f = r.uniform(0.6, 1.6, (3, TONGUES))  # each tongue's own rhythm
        self.tongue_p = r.uniform(0, TAU, (3, TONGUES))
        self.puff_tongue = r.integers(TONGUES, size=PUFFS)
        self.puff_rate = r.uniform(0.7, 1.4, PUFFS)  # puffs per second
        self.puff_phase = r.uniform(0, 1, PUFFS)
        self.spark_theta = r.uniform(0, TAU, SPARKS)
        self.spark_rate = r.uniform(0.35, 0.7, SPARKS)  # rises per second
        self.spark_phase = r.uniform(0, 1, SPARKS)

    def _tongues(self, sp: float) -> tuple[np.ndarray, np.ndarray]:
        """Each tongue's height (fraction of the tree) and angle round the trunk now."""
        f, p = self.tongue_f, self.tongue_p
        wobble = (0.55 * np.sin(TAU * f[0] * sp * 0.7 + p[0])
                  + 0.3 * np.sin(TAU * f[1] * sp * 1.9 + p[1])
                  + 0.15 * np.sin(TAU * f[2] * sp * 4.3 + p[2]))  # -1..1: rising and falling
        height = self.p["height"] * (0.6 + 0.4 * wobble)
        theta = self.tongue_theta + 0.25 * np.sin(TAU * f[1] * sp * 0.4 + p[2])  # swaying
        return height, theta

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        g, sp = m.geometry, self.p["speed"] * t
        span = max(float(g.hi[1] - g.lo[1]), 1e-6)
        h = (g.h - g.lo[1]) / span  # 0 at the bottom LED, 1 at the top
        th = g.theta

        # the bed of coals: a low band glowing and dimming in patches
        coals = np.clip(1 - h / 0.1, 0, 1) * (0.45 + 0.15 * np.sin(TAU * self.coal_f * t + self.coal_p))

        # tongues of flame: hot in the middle and near the bottom, narrowing to a tip
        heights, thetas = self._tongues(sp)
        dth = np.angle(np.exp(1j * (th[:, None] - thetas[None])))  # (N, tongues), -π..π
        up = np.clip(h[:, None] / heights[None], 0, 1.2)
        below = np.clip(1 - up, 0, 1)  # 1 at the bottom, 0 at (and above) the tip
        width = 0.38 * below**0.8 + 0.04  # radians each side, narrowing upwards
        tongue = np.exp(-((dth / width) ** 2)) * below**0.6
        heat = np.maximum(coals, tongue.max(axis=1))

        # puffs: blobs breaking off a tongue's tip, rising, shrinking and cooling
        life = (self.puff_phase + self.puff_rate * sp * 0.6) % 1.0
        tip = heights[self.puff_tongue]
        ph = tip * 0.85 + life * 0.25
        pt = thetas[self.puff_tongue] + 0.3 * np.sin(TAU * life + self.puff_phase * 7)
        size = 0.06 * (1 - life) + 0.015
        d2 = ((h[:, None] - ph[None]) / size[None]) ** 2 + (
            np.angle(np.exp(1j * (th[:, None] - pt[None]))) / (2.5 * size[None])) ** 2
        heat = np.maximum(heat, (0.75 * (1 - life)[None] * np.exp(-d2)).max(axis=1))

        k = self.p["sparks"]
        if k:  # sparks: tiny bright points flying up fast, zig-zagging
            rise = (self.spark_phase[:k] + self.spark_rate[:k] * sp) % 1.0
            sh = 0.1 + rise * 0.95
            st = self.spark_theta[:k] + 0.35 * np.sin(TAU * rise * 2.5 + self.spark_phase[:k] * 9)
            d2 = ((h[:, None] - sh[None]) / 0.025) ** 2 + (
                np.angle(np.exp(1j * (th[:, None] - st[None]))) / 0.12) ** 2
            heat = np.maximum(heat, (0.85 * (1 - rise[None]) * np.exp(-d2)).max(axis=1))
        return gradient_stops(FIRE, heat)


@register
class Blocks(_Effect3D):
    name = "blocks"
    label = "3D checkerboard"
    description = "The tree cut into cubes of two colours, the whole pattern turning round the trunk."
    params = (
        _color_param("color", "red"),
        _color_param("color2", "green", label="Second colour"),
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
        return np.where(first, xmas(self.p["color"]), xmas(self.p["color2"]))
