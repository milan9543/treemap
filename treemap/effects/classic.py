"""Classic strip effects that work along the LED index, like a controller's built-ins.

They need no map, so they run on a fresh tree before any scan. The position-aware ones are
in :mod:`treemap.effects.spatial`.
"""

from __future__ import annotations

import numpy as np

from treemap.effects import palettes as pal
from treemap.effects.base import (
    WARM_WHITE,
    Effect,
    Param,
    SparkleLayer,
    background_params,
    color_params,
    hsv_to_rgb,
)
from treemap.effects.registry import register


def _color(name: str, default: tuple[int, int, int], **kw) -> Param:
    return Param(name, "color", default, group="colours", **kw)


def _speed(default: float, lo: float, hi: float, unit: str = "LEDs/s", **kw) -> Param:
    return Param("speed", "float", default, min=lo, max=hi, step=kw.pop("step", 1), help=unit, **kw)


@register
class Solid(Effect):
    name = "solid"
    label = "Solid"
    description = "Every LED one colour."
    params = (_color("color", WARM_WHITE),)

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
        _color("color", (255, 0, 0)),
        _color("color2", (0, 0, 0), label="Second colour"),
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
        _color("color", (255, 255, 255)),
        *background_params(),
        _speed(8, 0.5, 60, "steps per second", step=0.5),
        Param("spacing", "int", 3, min=2, max=12, step=1),
    )

    def render(self, t):
        k = self.p["spacing"]
        lit = (np.arange(self.n) % k) == int(t * self.p["speed"]) % k
        return np.where(lit[:, None], self.color("color"), self.background())


@register
class CandyCane(Effect):
    name = "candy"
    label = "Candy cane"
    description = "Moving stripes of two colours."
    params = (
        _color("color", (255, 0, 0)),
        _color("color2", (255, 255, 255), label="Second colour"),
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
        _color("color", WARM_WHITE),
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
        *color_params((120, 180, 255), "rainbow", palette_help="each comet the next colour"),
        Param("count", "int", 3, min=1, max=30, step=1),
        _speed(60, 2, 600),
        Param("tail", "int", 25, min=1, max=200, step=1, help="tail length in LEDs"),
        *background_params(),
    )

    @classmethod
    def legacy(cls, values):
        values = super().legacy(values)
        if values.pop("rainbow", False) is True:
            values.update(colors="palette", palette="rainbow")
        return values

    def render(self, t):
        n, count = self.n, self.p["count"]
        heads = (t * self.p["speed"] + np.arange(count) * n / count) % n
        behind = (heads[:, None] - np.arange(n)[None, :]) % n  # (count, n) distance to head
        level = np.clip(1 - behind / self.p["tail"], 0, 1) ** 2
        colors = self.colors(np.arange(count))  # (count, 3)
        brightest = level.argmax(axis=0)  # where comets overlap, the brighter one shows
        return self.over_background(level.max(axis=0), colors[brightest])


@register
class Twinkle(Effect):
    name = "twinkle"
    label = "Twinkle"
    description = "Random LEDs fade in and out."
    sparkles = False  # it is sparkles
    params = (
        *color_params(WARM_WHITE, "christmas lights",
                      palette_help="each twinkle a colour from it, at random"),
        Param("rate", "float", 10.0, min=0.1, max=100, step=0.1,
              help="new twinkles per second per 100 LEDs"),
        Param("fade", "float", 1.2, min=0.1, max=8, step=0.1, help="seconds to fade out"),
        Param("base", "float", 0.0, min=0, max=0.5, step=0.01,
              help="background glow of every LED"),
    )

    OLD_PALETTES = {"warm": ("one", None), "color": ("one", None),
                    "christmas": ("palette", "christmas lights"), "rainbow": ("palette", "rainbow")}

    @classmethod
    def legacy(cls, values):
        values = super().legacy(values)
        old = values.get("palette")
        if old in cls.OLD_PALETTES and "colors" not in values:
            values["colors"], new = cls.OLD_PALETTES[old]
            if new:
                values["palette"] = new
            else:
                del values["palette"]
                if old == "warm":
                    values["color"] = WARM_WHITE
        return values

    def setup(self):
        self.age = np.full(self.n, np.inf, dtype=np.float32)
        self.lit = np.zeros((self.n, 3), dtype=np.float32)
        self.base_key = self._key()
        self.base_colors = self._palette(self.n)
        self.last_t = 0.0

    def _key(self) -> tuple:
        return self.p["colors"], self.palette().tobytes()

    def _palette(self, k: int) -> np.ndarray:
        if self.p["colors"] == "one":
            return np.broadcast_to(self.color("color"), (k, 3)).copy()
        return pal.random(self.palette(), self.rng, k)

    def render(self, t):
        dt = max(t - self.last_t, 0.0)
        self.last_t = t
        self.age += dt
        idle = np.flatnonzero(self.age > self.p["fade"] + 0.15)
        spawn = min(self.rng.poisson(self.p["rate"] * self.n / 100 * dt), len(idle))
        if spawn:
            pick = self.rng.choice(idle, spawn, replace=False)
            self.age[pick] = 0
            self.lit[pick] = self._palette(spawn)
        attack = 0.15
        level = np.where(
            self.age < attack, self.age / attack, np.exp(-3 * (self.age - attack) / self.p["fade"])
        )
        if self.p["colors"] == "one":
            base = self.color("color")  # follows colour changes live
            frame = level[:, None] * base
            return np.maximum(frame, base * self.p["base"])
        if self._key() != self.base_key:  # palette changed while running
            self.base_key, self.base_colors = self._key(), self._palette(self.n)
        return np.maximum(level[:, None] * self.lit, self.base_colors * self.p["base"])


@register
class Sparkle(Effect):
    name = "sparkle"
    label = "Sparkle"
    description = "A steady background with brief random flashes."
    sparkles = False  # it is sparkles
    params = (
        *background_params((150, 62, 0), level=0.4),
        *color_params((255, 255, 255), "christmas lights",
                      palette_help="each flash a colour from it, at random"),
        Param("rate", "float", 15.0, min=0.5, max=200, step=0.5,
              help="flashes per second per 100 LEDs"),
        Param("length", "float", 0.08, min=0.02, max=1, step=0.01, help="seconds per flash"),
    )

    def setup(self):
        self.layer = SparkleLayer(self.n, self.rng)

    def render(self, t):
        colors = self.color("color")[None] if self.p["colors"] == "one" else self.palette()
        level, rgb = self.layer.level(t, self.p["rate"], self.p["length"], colors)
        return self.over_background(level, rgb)


@register
class Flicker(Effect):
    name = "flicker"
    label = "Candle flicker"
    description = "Every LED flickers gently and independently, like candles."
    params = (
        _color("color", (255, 120, 25)),
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
