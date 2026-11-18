"""Diagnostic effects for checking wiring and index order."""

from __future__ import annotations

import numpy as np

from treemap.effects.base import Effect, Param
from treemap.effects.registry import register


@register
class Chase(Effect):
    name = "chase"
    label = "Index chase"
    group = "Diagnostics"
    description = "A light running from LED 0 to the last LED, over and over."
    params = (
        Param("color", "color", (255, 255, 255)),
        Param("speed", "float", 20, min=1, max=400, step=1, help="LEDs per second"),
        Param("width", "int", 3, min=1, max=50, step=1, help="lit LEDs, fading behind the head"),
    )

    def render(self, t):
        head = (t * self.p["speed"]) % self.n
        behind = (head - np.arange(self.n)) % self.n
        level = np.clip(1 - np.floor(behind) / self.p["width"], 0, 1)
        return level[:, None] * self.color("color")


@register
class Markers(Effect):
    name = "markers"
    label = "Index markers"
    group = "Diagnostics"
    description = (
        "LED 0 blue, every 100th green, every 50th red, every 10th dim white: "
        "read the index order off the tree."
    )
    params = (Param("brightness", "float", 1.0, min=0.05, max=1, step=0.05),)

    def render(self, t):
        i = np.arange(self.n)
        frame = self.blank()
        frame[i % 10 == 0] = (60, 60, 60)
        frame[i % 50 == 0] = (255, 0, 0)
        frame[i % 100 == 0] = (0, 255, 0)
        frame[0] = (0, 80, 255)
        return frame * self.p["brightness"]


@register
class SingleLed(Effect):
    name = "led"
    label = "Single LED"
    group = "Diagnostics"
    description = "Light one LED by index, its neighbours dimly."
    params = (
        Param("index", "int", 0, min=0, step=1, max_is_last_led=True),
        Param("color", "color", (255, 255, 255)),
        Param("neighbours", "bool", True, help="light the LEDs either side at 10%"),
    )

    def render(self, t):
        frame = self.blank()
        i, c = self.p["index"], self.color("color")
        if self.p["neighbours"]:
            frame[max(i - 1, 0) : i + 2] = c * 0.1
        frame[i] = c
        return frame
