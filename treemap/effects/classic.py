"""Classic strip effects that work along the LED index, like a controller's built-ins.

They need no map, so they run on a fresh tree before any scan. Position-aware 3D effects
(planes, spirals, ...) arrive with the mapped tree.
"""

from __future__ import annotations

import numpy as np

from treemap.effects.base import Effect, Param, hsv_to_rgb
from treemap.effects.registry import register

WARM_WHITE = (255, 150, 60)
CHRISTMAS = np.array(
    [(255, 0, 0), (0, 200, 0), (0, 60, 255), (255, 160, 0), (255, 40, 120), (255, 255, 255)],
    dtype=np.float32,
)


def _speed(default: float, lo: float, hi: float, unit: str = "LEDs/s", **kw) -> Param:
    return Param("speed", "float", default, min=lo, max=hi, step=kw.pop("step", 1), help=unit, **kw)


@register
class Solid(Effect):
    name = "solid"
    label = "Solid"
    description = "Every LED one colour."
    params = (Param("color", "color", WARM_WHITE),)

    def render(self, t):
        return np.broadcast_to(self.color("color"), (self.n, 3))


@register
class Rainbow(Effect):
    name = "rainbow"
    label = "Rainbow"
    description = "A rainbow running along the strips."
    params = (
        _speed(0.15, -2, 2, "rainbow cycles per second", step=0.01),
        Param("repeats", "float", 1.0, min=0.1, max=20, step=0.1,
              help="how many rainbows fit along all the LEDs"),
        Param("saturation", "float", 1.0, min=0, max=1, step=0.01),
    )

    def render(self, t):
        hue = np.arange(self.n) / self.n * self.p["repeats"] + t * self.p["speed"]
        return hsv_to_rgb(hue, self.p["saturation"])


@register
class ColorLoop(Effect):
    name = "colorloop"
    label = "Colour loop"
    description = "The whole tree slowly fades through the hues together."
    params = (
        _speed(0.05, 0.005, 1, "hue cycles per second", step=0.005),
        Param("saturation", "float", 1.0, min=0, max=1, step=0.01),
    )

    def render(self, t):
        rgb = hsv_to_rgb(np.array([t * self.p["speed"]]), self.p["saturation"])[0]
        return np.broadcast_to(rgb, (self.n, 3))


@register
class Wipe(Effect):
    name = "wipe"
    label = "Colour wipe"
    description = "Fills the LEDs one by one with a colour, then with the second colour."
    params = (
        Param("color", "color", (255, 0, 0)),
        Param("color2", "color", (0, 0, 0), label="Second colour"),
        _speed(60, 1, 1000),
    )

    def render(self, t):
        pos = (t * self.p["speed"]) % (2 * self.n)
        first, second = self.color("color"), self.color("color2")
        if pos >= self.n:
            first, second, pos = second, first, pos - self.n
        # Fractional head so slow wipes move smoothly.
        fill = np.clip(pos - np.arange(self.n), 0.0, 1.0)[:, None]
        return fill * first + (1 - fill) * second


@register
class Theater(Effect):
    name = "theater"
    label = "Theatre chase"
    description = "Every Nth LED lit, marching along like cinema marquee lights."
    params = (
        Param("color", "color", (255, 255, 255)),
        Param("background", "color", (0, 0, 0)),
        _speed(8, 0.5, 60, "steps per second", step=0.5),
        Param("spacing", "int", 3, min=2, max=12, step=1),
    )

    def render(self, t):
        k = self.p["spacing"]
        lit = (np.arange(self.n) % k) == int(t * self.p["speed"]) % k
        return np.where(lit[:, None], self.color("color"), self.color("background"))


@register
class CandyCane(Effect):
    name = "candy"
    label = "Candy cane"
    description = "Moving stripes of two colours."
    params = (
        Param("color", "color", (255, 0, 0)),
        Param("color2", "color", (255, 255, 255), label="Second colour"),
        Param("width", "int", 6, min=1, max=60, step=1, help="LEDs per stripe"),
        _speed(8, -100, 100),
    )

    def render(self, t):
        w = self.p["width"]
        stripe = np.floor((np.arange(self.n) - t * self.p["speed"]) / w).astype(int) % 2
        return np.where(stripe[:, None] == 0, self.color("color"), self.color("color2"))


@register
class Breathe(Effect):
    name = "breathe"
    label = "Breathe"
    description = "The whole tree slowly pulses."
    params = (
        Param("color", "color", WARM_WHITE),
        Param("period", "float", 4.0, min=0.5, max=30, step=0.1, help="seconds per breath"),
        Param("floor", "float", 0.05, min=0, max=1, step=0.01, help="dimmest level"),
    )

    def render(self, t):
        wave = (0.5 - 0.5 * np.cos(2 * np.pi * t / self.p["period"])) ** 2
        level = self.p["floor"] + (1 - self.p["floor"]) * wave
        return np.broadcast_to(self.color("color") * level, (self.n, 3))


@register
class Comets(Effect):
    name = "comets"
    label = "Comets"
    description = "Bright heads with fading tails running along the strips."
    params = (
        Param("color", "color", (120, 180, 255)),
        Param("count", "int", 3, min=1, max=30, step=1),
        _speed(60, 2, 600),
        Param("tail", "int", 25, min=1, max=200, step=1, help="tail length in LEDs"),
        Param("rainbow", "bool", False, help="give each comet its own, shifting colour"),
    )

    def render(self, t):
        n, count = self.n, self.p["count"]
        heads = (t * self.p["speed"] + np.arange(count) * n / count) % n
        behind = (heads[:, None] - np.arange(n)[None, :]) % n  # (count, n) distance to head
        level = np.clip(1 - behind / self.p["tail"], 0, 1) ** 2
        if self.p["rainbow"]:
            colors = hsv_to_rgb(np.arange(count) / count + t * 0.05)  # (count, 3)
        else:
            colors = np.broadcast_to(self.color("color"), (count, 3))
        return (level[:, :, None] * colors[:, None, :]).max(axis=0)


@register
class Twinkle(Effect):
    name = "twinkle"
    label = "Twinkle"
    description = "Random LEDs fade in and out."
    params = (
        Param("palette", "choice", "warm", choices=("warm", "christmas", "rainbow", "color")),
        Param("color", "color", (255, 255, 255), help="used by the 'color' palette"),
        Param("rate", "float", 10.0, min=0.1, max=100, step=0.1,
              help="new twinkles per second per 100 LEDs"),
        Param("fade", "float", 1.2, min=0.1, max=8, step=0.1, help="seconds to fade out"),
        Param("base", "float", 0.0, min=0, max=0.5, step=0.01,
              help="background glow of every LED"),
    )

    def setup(self):
        self.age = np.full(self.n, np.inf, dtype=np.float32)
        self.colors = np.zeros((self.n, 3), dtype=np.float32)
        self.base_colors = self._palette(self.n)
        self.base_palette = self.p["palette"]
        self.last_t = 0.0

    def _palette(self, k: int) -> np.ndarray:
        pal = self.p["palette"]
        if pal == "warm":
            return np.broadcast_to(np.float32(WARM_WHITE), (k, 3)).copy()
        if pal == "christmas":
            return CHRISTMAS[self.rng.integers(0, len(CHRISTMAS), k)]
        if pal == "rainbow":
            return hsv_to_rgb(self.rng.random(k))
        return np.broadcast_to(self.color("color"), (k, 3)).copy()

    def render(self, t):
        dt = max(t - self.last_t, 0.0)
        self.last_t = t
        self.age += dt
        idle = np.flatnonzero(self.age > self.p["fade"] + 0.15)
        spawn = min(self.rng.poisson(self.p["rate"] * self.n / 100 * dt), len(idle))
        if spawn:
            pick = self.rng.choice(idle, spawn, replace=False)
            self.age[pick] = 0
            self.colors[pick] = self._palette(spawn)
        attack = 0.15
        level = np.where(
            self.age < attack, self.age / attack, np.exp(-3 * (self.age - attack) / self.p["fade"])
        )
        if self.p["palette"] in ("warm", "color"):
            base = self._palette(1)[0]  # follows colour changes live
            frame = level[:, None] * base
            return np.maximum(frame, base * self.p["base"])
        if self.p["palette"] != self.base_palette:  # palette changed while running
            self.base_colors, self.base_palette = self._palette(self.n), self.p["palette"]
        return np.maximum(level[:, None] * self.colors, self.base_colors * self.p["base"])


@register
class Sparkle(Effect):
    name = "sparkle"
    label = "Sparkle"
    description = "A steady background with brief random flashes."
    params = (
        Param("background", "color", (60, 25, 0)),
        Param("color", "color", (255, 255, 255), label="Flash colour"),
        Param("rate", "float", 15.0, min=0.5, max=200, step=0.5,
              help="flashes per second per 100 LEDs"),
        Param("length", "float", 0.08, min=0.02, max=1, step=0.01, help="seconds per flash"),
    )

    def setup(self):
        self.until = np.zeros(self.n, dtype=np.float32)
        self.last_t = 0.0

    def render(self, t):
        dt = max(t - self.last_t, 0.0)
        self.last_t = t
        k = min(self.rng.poisson(self.p["rate"] * self.n / 100 * dt), self.n)
        if k:
            self.until[self.rng.choice(self.n, k, replace=False)] = t + self.p["length"]
        on = (self.until > t)[:, None]
        return np.where(on, self.color("color"), self.color("background"))


@register
class Flicker(Effect):
    name = "flicker"
    label = "Candle flicker"
    description = "Every LED flickers gently and independently, like candles."
    params = (
        Param("color", "color", (255, 120, 25)),
        Param("amount", "float", 0.45, min=0, max=1, step=0.01, help="flicker depth"),
        _speed(5.0, 0.2, 30, "flickers per second", step=0.1),
    )

    def setup(self):
        self.freq = self.rng.uniform(0.6, 1.6, (self.n, 3)).astype(np.float32)
        self.phase = self.rng.uniform(0, 2 * np.pi, (self.n, 3)).astype(np.float32)

    def render(self, t):
        x = 2 * np.pi * self.p["speed"] * t * self.freq + self.phase
        noise = np.sin(x).mean(axis=1) * 0.5 + 0.5  # 0..1, smooth, per LED
        level = 1 - self.p["amount"] * noise**2
        return level[:, None] * self.color("color")
