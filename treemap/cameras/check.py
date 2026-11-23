"""Checks that the phone's camera reads the code's colours, before a scan.

The LEDs show each colour of the scan code in turn (red, green, blue, and the white of
the sync), at the scan's brightness, and the scan's own blob finder reads them; the
share of blobs it reads as the right colour is what decides whether a scan will work.

Phones film the LEDs' colours washed out, so the colours are measured as this camera
sees them (:mod:`treemap.scan.colours`), saved, and the scan reads colours by them.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from treemap.cameras.base import Camera
from treemap.outputs.base import LedOutput
from treemap.scan.code import SYMBOL_RGB, SYNC
from treemap.scan.colours import ColourError, ColourModel
from treemap.scan.track import find_blobs

COLOURS = {"red": 0, "green": 1, "blue": 2, "white": SYNC}
SYMBOL_NAMES = {0: "red", 1: "green", 2: "blue", SYNC: "white", -1: "unclear"}
GOOD_SHARE = 0.85  # of blobs read as the right colour (the check digit and votes do the rest)
NEAR_WHITE = 0.06  # chromaticity distance below which a colour is hard to tell from white
DIM_SHARE = 0.7  # a colour seen in fewer LEDs than this share of white's is too dim


def solid(n: int, symbol: int, brightness: int) -> np.ndarray:
    """Every LED showing one symbol's colour at the scan's brightness."""
    return np.tile(np.round(SYMBOL_RGB[symbol] * brightness).astype(np.uint8), (n, 1))


def mixed(n: int, brightness: int) -> np.ndarray:
    """Every LED in one of the code's colours, in turn along the strip (red, green, blue,
    white, red, …), at the scan's brightness: an exposure that shows all of them shows
    the dimmest colour too, which white alone doesn't tell."""
    return np.round(SYMBOL_RGB[np.arange(n) % len(COLOURS)] * brightness).astype(np.uint8)


def read_for(camera: Camera, seconds: float) -> list:
    """Every frame that arrives in the next ``seconds``."""
    frames = []
    end = time.monotonic() + seconds
    while (left := end - time.monotonic()) > 0:
        f = camera.read(timeout=min(left, 0.1))
        if f is not None:
            frames.append(f)
    return frames


@dataclass
class ColourResult:
    name: str
    blobs: int  # median per frame
    share: float  # of blobs read as this colour with the measured colours (NaN if none)
    misread_as: str | None  # the commonest wrong reading
    sample: np.ndarray | None  # one frame, BGR


def colour_check(camera: Camera, output: LedOutput, brightness: int, settle_s: float = 0.6,
                 sample_s: float = 1.5, on_colour: Callable[[int], None] = lambda i: None,
                 ) -> tuple[list[ColourResult], ColourModel | None]:
    """Show each colour on every LED and measure how the camera sees it. The colours are
    measured on half the frames and tested on the other half, so the shares are what a
    scan can expect. Returns the results and the measured colours (None if some colour
    wasn't seen at all). ``on_colour(i)`` runs as the i-th colour starts showing (and may
    raise to stop)."""
    seen: dict[str, list] = {}
    samples: dict[str, np.ndarray | None] = {}
    for i, (name, sym) in enumerate(COLOURS.items()):
        on_colour(i)
        output.show(solid(output.led_count, sym, brightness))
        read_for(camera, settle_s)  # frames from before the change
        frames = read_for(camera, sample_s)
        seen[name] = [find_blobs(f.image).rgb for f in frames]
        samples[name] = frames[len(frames) // 2].image if frames else None
    output.off()

    fit = {n: np.concatenate(b[0::2] or [np.zeros((0, 3))]) for n, b in seen.items()}
    try:
        model = ColourModel.fit(fit, brightness=brightness)
    except ColourError:
        model = None
    results = []
    for name, sym in COLOURS.items():
        test = seen[name][1::2] or seen[name]
        rgb = np.concatenate(test or [np.zeros((0, 3))])
        syms = model.classify(rgb) if model is not None else np.zeros(0, int)
        wrong = syms[syms != sym]
        worst = Counter(wrong.tolist()).most_common(1)
        results.append(ColourResult(
            name=name,
            blobs=int(np.median([len(b) for b in seen[name]])) if seen[name] else 0,
            share=float(np.mean(syms == sym)) if len(syms) else float("nan"),
            misread_as=SYMBOL_NAMES[worst[0][0]] if worst else None,
            sample=samples[name],
        ))
    return results, model


def advice(results: list[ColourResult], model: ColourModel | None, brightness: int) -> list[str]:
    """What to change, if anything; empty if the camera is fit to scan."""
    tips = []
    few = [r.name for r in results if r.blobs < 10]
    if few:
        tips.append(f"few LEDs seen in {', '.join(few)}: point the phone at the LEDs, from "
                    "close enough that they don't blur together.")
    white = next((r.blobs for r in results if r.name == "white"), 0)
    for r in results:
        if r.name != "white" and r.name not in few and r.blobs < DIM_SHARE * white:
            tips.append(f"{r.name} looks dim to the camera: {r.blobs} LEDs seen, against "
                        f"{white} in white, so LEDs are lost while they show it. A longer "
                        f"exposure or a higher scan.brightness (now {brightness}) helps.")
    if model is not None:
        for name in ("red", "green", "blue"):
            if model.distance(name, "white") < NEAR_WHITE:
                tips.append(f"{name} looks almost white to the camera: it's overexposed. "
                            f"Lower scan.brightness (now {brightness}) or the exposure.")
    for r in results:
        if r.blobs >= 10 and not r.share >= GOOD_SHARE:
            tips.append(f"{r.name} is read right only {r.share:.0%} of the time (else as "
                        f"{r.misread_as}): darken the room and keep the phone still.")
    return tips
