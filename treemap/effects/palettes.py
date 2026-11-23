"""Palettes: lists of colours that effects draw from.

A palette is just colours, in order. Each effect decides how to use them: as a loop that
colour flows round (:func:`loop`), as a ramp from the first colour to the last
(:func:`ramp`), one after another (:func:`pick`) or at random (:func:`random`).

The presets below are built in. Custom palettes are kept by the server's library
(:mod:`treemap.library`) and reach effects through ``EffectContext.palettes``. A
palette parameter holds a palette's id, so editing a custom palette changes every
effect that uses it.
"""

from __future__ import annotations

import re

import numpy as np

RGB = tuple[int, int, int]

# The Christmas colours: defaults and swatches. Their names also work as colour values.
XMAS: dict[str, RGB] = {
    "red": (255, 0, 0),
    "green": (0, 190, 20),
    "gold": (255, 140, 0),
    "warm white": (255, 150, 60),
    "white": (255, 255, 255),
}

# id -> (name, colours). The ids are what favourites store, so they never change.
PRESETS: dict[str, tuple[str, list[RGB]]] = {
    "christmas": ("Christmas", [XMAS["red"], XMAS["gold"], XMAS["green"], XMAS["white"]]),
    "candy cane": ("Candy cane", [XMAS["red"], XMAS["white"]]),
    "red & green": ("Red & green", [XMAS["red"], XMAS["green"]]),
    "green & gold": ("Green & gold", [XMAS["green"], XMAS["gold"]]),
    "gold": ("Gold", [XMAS["gold"], XMAS["warm white"]]),
    "christmas lights": ("Christmas lights", [(255, 0, 0), (0, 200, 0), (0, 60, 255),
                                              (255, 160, 0), (255, 40, 120), (255, 255, 255)]),
    "rainbow": ("Rainbow", [(255, 0, 0), (255, 200, 0), (0, 255, 0), (0, 200, 255),
                            (0, 0, 255), (200, 0, 255)]),
    "snow": ("Snow", [XMAS["white"]]),
    "icy": ("Icy", [(255, 255, 255), (120, 180, 255), (40, 80, 255)]),
    # dark to bright, for effects that ramp from the first colour to the last
    "christmas dusk": ("Christmas dusk", [(60, 0, 0), (255, 0, 0), (255, 140, 0),
                                          (0, 190, 20), (0, 50, 5)]),
    "candlelight": ("Candlelight", [(0, 0, 0), (120, 0, 0), (255, 40, 0), (255, 140, 0),
                                    (255, 200, 120)]),
    "fir": ("Fir", [(0, 10, 0), (0, 80, 10), (0, 190, 20), (220, 150, 0), (255, 190, 90)]),
    "candy glow": ("Candy glow", [(60, 0, 0), (255, 0, 0), (255, 80, 80), (255, 255, 255)]),
}

CUSTOM_ID = re.compile(r"my-[0-9a-f]{8}")
MAX_COLORS = 16


def is_palette_id(value: object) -> bool:
    return isinstance(value, str) and (value in PRESETS or bool(CUSTOM_ID.fullmatch(value)))


def preset(pid: str) -> np.ndarray | None:
    entry = PRESETS.get(pid)
    return None if entry is None else stops(entry[1])


def stops(colors: list[RGB] | np.ndarray) -> np.ndarray:
    return np.asarray(colors, dtype=np.float32).reshape(-1, 3)


def loop(colors: np.ndarray, s: np.ndarray) -> np.ndarray:
    """Colours 0-255 round the palette as a loop for ``s`` (one loop per 1): ``s.shape + (3,)``."""
    looped = np.concatenate([colors, colors[:1]])
    x = np.linspace(0, 1, len(looped))
    s = np.mod(s, 1.0)
    return np.stack([np.interp(s, x, looped[:, c]) for c in range(3)], axis=-1).astype(np.float32)


def ramp(colors: np.ndarray, s: np.ndarray) -> np.ndarray:
    """Colours 0-255 from the first colour (``s`` 0) to the last (1), clipped."""
    if len(colors) == 1:
        return np.broadcast_to(colors[0], np.shape(s) + (3,)).astype(np.float32)
    x = np.linspace(0, 1, len(colors))
    s = np.clip(s, 0, 1)
    return np.stack([np.interp(s, x, colors[:, c]) for c in range(3)], axis=-1).astype(np.float32)


def pick(colors: np.ndarray, k: np.ndarray | float | int) -> np.ndarray:
    """The ``k``-th colour, going round the palette."""
    return colors[np.asarray(k, dtype=np.int64) % len(colors)]


def random(colors: np.ndarray, rng: np.random.Generator, k: int) -> np.ndarray:
    """``k`` colours picked from the palette at random: ``(k, 3)``."""
    return colors[rng.integers(0, len(colors), k)]


def describe_presets() -> list[dict]:
    return [{"id": pid, "name": name, "colors": [to_hex(c) for c in colors], "preset": True}
            for pid, (name, colors) in PRESETS.items()]


def to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(int(c) for c in rgb))
