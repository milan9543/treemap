"""Checks that a camera can scan: frame rate, and whether it reads the code's colours.

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
MIN_FPS = 15.0  # below this, a symbol of scan.symbol_ms (150) gets too few frames
GOOD_SHARE = 0.85  # of blobs read as the right colour (the check digit and votes do the rest)
NEAR_WHITE = 0.06  # chromaticity distance below which a colour is hard to tell from white


def solid(n: int, symbol: int, brightness: int) -> np.ndarray:
    """Every LED showing one symbol's colour at the scan's brightness."""
    return np.tile(np.round(SYMBOL_RGB[symbol] * brightness).astype(np.uint8), (n, 1))


def read_for(camera: Camera, seconds: float) -> list:
    """Every frame that arrives in the next ``seconds``."""
    frames = []
    end = time.monotonic() + seconds
    while (left := end - time.monotonic()) > 0:
        f = camera.read(timeout=min(left, 0.1))
        if f is not None:
            frames.append(f)
    return frames


EXPOSURES_NS = (500_000, 1_000_000, 2_000_000, 4_000_000, 8_000_000, 16_000_000)
ISO = 100
ENOUGH = 0.9  # of the most LEDs any exposure sees


def fix_exposure(camera: Camera, output: LedOutput, brightness: int,
                 seconds: float = 2.5) -> str | None:
    """Fix the camera's exposure and white balance for the scan, so colours don't drift
    while the LEDs flash. The LEDs show white at the scan's brightness (the brightest
    the code gets) meanwhile. Only for cameras that can (the Android one); returns what
    was done, or None if there's nothing it can do.

    - Manual exposure (IP Webcam on most phones): try each of EXPOSURES_NS and keep the
      shortest that sees nearly as many LEDs as the best; shorter clips less.
    - Exposure lock (older phones): let automatic exposure adjust, then lock it.
    """
    state = camera.exposure() if hasattr(camera, "exposure") else None
    if state is None or state["kind"] is None:
        return None
    output.show(solid(output.led_count, SYNC, brightness))
    if state["kind"] == "manual":
        camera.lock(True, exposure=False)  # white balance
        seen = []
        for ns in EXPOSURES_NS:
            if not camera.set_exposure(ns, ISO):
                return "couldn't set the exposure; set it in IP Webcam"
            read_for(camera, 0.7)  # frames from before the change
            counts = [len(find_blobs(f.image)) for f in read_for(camera, 0.4)]
            seen.append(int(np.median(counts)) if counts else 0)
        if max(seen) == 0:
            camera.set_exposure(EXPOSURES_NS[2], ISO)
            return "no LEDs seen at any exposure: point the phone at the LEDs"
        best = next(ns for ns, k in zip(EXPOSURES_NS, seen) if k >= ENOUGH * max(seen))
        camera.set_exposure(best, ISO)
        read_for(camera, 0.7)
        return (f"exposure {best / 1e6:g} ms at ISO {ISO} (LEDs seen per exposure: "
                + ", ".join(f"{ns / 1e6:g} ms {k}" for ns, k in zip(EXPOSURES_NS, seen)) + ")")
    camera.lock(False)
    read_for(camera, seconds)  # keep the stream flowing while it adjusts
    ok = camera.lock(True)
    return "adjusted exposure and white balance to the LEDs, then locked them" if ok else \
        "couldn't lock exposure and white balance; lock them in IP Webcam"


@dataclass
class ColourResult:
    name: str
    blobs: int  # median per frame
    share: float  # of blobs read as this colour with the measured colours (NaN if none)
    misread_as: str | None  # the commonest wrong reading
    sample: np.ndarray | None  # one frame, BGR


def measure_fps(camera: Camera, seconds: float = 3.0) -> tuple[float, tuple[int, int] | None]:
    frames = read_for(camera, seconds)
    if len(frames) < 2:
        return 0.0, None
    h, w = frames[-1].image.shape[:2]
    return (len(frames) - 1) / max(frames[-1].t - frames[0].t, 1e-6), (w, h)


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


def advice(fps: float | None, size: tuple[int, int] | None, results: list[ColourResult],
           model: ColourModel | None, brightness: int) -> list[str]:
    """What to change, if anything; empty if the camera is fit to scan. ``fps`` None:
    not measured (the scan page's camera, whose frame rate it shows itself)."""
    tips = []
    if fps is not None and fps < MIN_FPS:
        tips.append(f"only {fps:.0f} frames/s; the scan needs {MIN_FPS:.0f}+ (24 is better). "
                    "Lower IP Webcam's video resolution or quality (Video preferences).")
    if size is not None and size[0] > 1280:
        tips.append(f"frames are {size[0]}x{size[1]}; 1280x720 or 640x480 is plenty and "
                    "faster to send and to read.")
    few = [r.name for r in results if r.blobs < 10]
    if few:
        tips.append(f"few LEDs seen in {', '.join(few)}: point the phone at the LEDs, from "
                    "close enough that they don't blur together.")
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
