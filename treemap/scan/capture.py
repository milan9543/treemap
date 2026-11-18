"""Scan capture: light each LED in turn and find it in the camera's view.

The same loop drives the simulator and the real tree; it only sees an ``LedOutput`` and
a ``Camera``. For each view angle:

1. turn everything off and take a dark reference;
2. for each LED: light it, wait for it to settle, photograph, subtract the dark
   reference and detect the blob;
3. flash the LEDs that were found green, so you can see what the camera saw.

Results go to ``<scan_dir>/angle_XXX.json`` (see :class:`AngleScan`), saved as the scan
goes, so an interrupted scan resumes where it stopped. Alongside it:

* ``angle_XXX_dark.png``: the dark reference;
* ``angle_XXX_exposure.png``: every LED's difference image combined (a long exposure);
* ``angle_XXX_debug.png``: that exposure with the detections drawn on.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from treemap.cameras.base import Camera
from treemap.outputs.base import LedOutput
from treemap.scan.detect import Detection, detect

FORMAT_VERSION = 1
STATUSES = ("ok", "weak", "missing")  # weak: found, but below min_confidence
SAVE_EVERY = 10  # LEDs between saves while scanning
FLASH_COLOR = (0, 120, 0)

ProgressFn = Callable[[int, int, int, dict], None]  # (done, total, led index, entry)


class ScanError(RuntimeError):
    """A scan can't start or continue (e.g. results from a different camera setup)."""


def angle_name(angle: float) -> str:
    """File stem for a view angle: ``angle_000`` ... ``angle_359`` (whole degrees)."""
    return f"angle_{round(angle) % 360:03d}"


@dataclass
class AngleScan:
    """Detections for one view angle.

    ``leds`` maps LED index to ``{"status", "u", "v", "confidence"}``: ``ok`` and
    ``weak`` have pixel coordinates, ``missing`` has ``u = v = None``. LEDs not scanned
    yet are absent.
    """

    angle: float
    led_count: int
    image_size: tuple[int, int]  # (width, height) px
    min_confidence: float
    leds: dict[int, dict[str, Any]] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        out = dict.fromkeys(STATUSES, 0)
        for e in self.leds.values():
            out[e["status"]] += 1
        return out

    def ok_indices(self) -> list[int]:
        return sorted(i for i, e in self.leds.items() if e["status"] == "ok")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "angle": self.angle,
            "led_count": self.led_count,
            "image_size": list(self.image_size),
            "min_confidence": self.min_confidence,
            "counts": self.counts(),
            "leds": {str(i): self.leds[i] for i in sorted(self.leds)},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AngleScan:
        if d.get("version") != FORMAT_VERSION:
            raise ScanError(f"unsupported scan format version {d.get('version')!r}")
        return cls(
            angle=float(d["angle"]),
            led_count=int(d["led_count"]),
            image_size=(int(d["image_size"][0]), int(d["image_size"][1])),
            min_confidence=float(d["min_confidence"]),
            leds={int(k): v for k, v in d["leds"].items()},
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=1))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> AngleScan:
        return cls.from_dict(json.loads(path.read_text()))


def load_scans(scan_dir: Path) -> list[AngleScan]:
    """Every angle scanned so far in ``scan_dir``, by angle."""
    scans = [AngleScan.load(p) for p in sorted(scan_dir.glob("angle_[0-9][0-9][0-9].json"))]
    return sorted(scans, key=lambda s: s.angle % 360)


def parse_leds(text: str, led_count: int) -> list[int]:
    """``"120-140"``, ``"5"`` or ``"1-3,7,10-12"`` (inclusive) as sorted indices."""
    out: set[int] = set()
    for part in text.split(","):
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
        if not m:
            raise ValueError(f"{text!r}: expected ranges like 120-140 or 1-3,7,10-12")
        a = int(m[1])
        b = int(m[2]) if m[2] is not None else a
        if a > b:
            raise ValueError(f"{part.strip()!r}: range runs backwards")
        if b >= led_count:
            raise ValueError(f"{part.strip()!r}: LEDs go up to {led_count - 1}")
        out.update(range(a, b + 1))
    return sorted(out)


def _entry(det: Detection | None, min_confidence: float) -> dict[str, Any]:
    if det is None:
        return {"status": "missing", "u": None, "v": None, "confidence": 0.0}
    status = "ok" if det.confidence >= min_confidence else "weak"
    return {"status": status, "u": round(det.u, 2), "v": round(det.v, 2),
            "confidence": det.confidence}


def scan_angle(
    output: LedOutput,
    camera: Camera,
    angle: float,
    scan_dir: Path,
    *,
    leds: Iterable[int] | None = None,
    fresh: bool = False,
    settle_s: float = 0.15,
    brightness: int = 255,
    min_confidence: float = 0.3,
    flash_s: float = 1.5,
    on_progress: ProgressFn | None = None,
) -> AngleScan:
    """Scan one view angle; the camera must already be pointing at it.

    ``leds=None`` scans every LED not yet in the saved results (all of them if
    ``fresh``); explicit ``leds`` are (re)scanned even if already done. Results are
    saved as it goes and on interruption, so the same call resumes it.
    """
    n = output.led_count
    stem = scan_dir / angle_name(angle)
    json_path = stem.with_suffix(".json")
    exposure_path = stem.parent / f"{stem.name}_exposure.png"

    result = None
    if json_path.exists() and not fresh:
        result = AngleScan.load(json_path)
        if result.led_count != n:
            raise ScanError(
                f"{json_path} was scanned with {result.led_count} LEDs, not {n}; "
                "rescan it with --fresh"
            )

    output.off()
    time.sleep(settle_s)
    dark = camera.capture()
    h, w = dark.shape[:2]
    if result is None:
        result = AngleScan(angle, n, (w, h), min_confidence)
    elif result.image_size != (w, h):
        raise ScanError(
            f"{json_path} has {result.image_size[0]}x{result.image_size[1]} photos but the "
            f"camera now takes {w}x{h}; rescan it with --fresh"
        )
    result.angle, result.min_confidence = angle, min_confidence
    scan_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(stem.parent / f"{stem.name}_dark.png"), dark)

    exposure = cv2.imread(str(exposure_path)) if exposure_path.exists() and not fresh else None
    if exposure is None or exposure.shape != dark.shape:
        exposure = np.zeros_like(dark)

    todo = sorted(set(leds)) if leds is not None else [i for i in range(n) if i not in result.leds]
    frame = np.zeros((n, 3), dtype=np.uint8)
    try:
        for k, i in enumerate(todo, 1):
            frame[:] = 0
            frame[i] = brightness
            output.show(frame)
            time.sleep(settle_s)
            lit = camera.capture()
            entry = _entry(detect(lit, dark), min_confidence)
            result.leds[i] = entry
            cv2.max(exposure, cv2.subtract(lit, dark), dst=exposure)
            if k % SAVE_EVERY == 0:
                result.save(json_path)
            if on_progress:
                on_progress(k, len(todo), i, entry)
    finally:
        output.off()
        result.save(json_path)
        cv2.imwrite(str(exposure_path), exposure)
        cv2.imwrite(str(stem.parent / f"{stem.name}_debug.png"), debug_overlay(dark, exposure, result))

    if flash_s > 0:
        frame[:] = 0
        frame[result.ok_indices()] = FLASH_COLOR
        output.show(frame)
        time.sleep(flash_s)
        output.off()
    return result


def debug_overlay(dark: np.ndarray, exposure: np.ndarray, scan: AngleScan) -> np.ndarray:
    """The long exposure with detections marked: green ok, orange weak, every 10th
    found LED labelled, consecutive ok LEDs joined to show the wiring order."""
    h, w = dark.shape[:2]
    scale = float(np.clip(1280 / max(h, w), 0.5, 3.0))
    base = cv2.add(dark, exposure)
    img = cv2.resize(base, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_LINEAR)

    def pt(e: dict) -> tuple[int, int]:
        return round(e["u"] * scale), round(e["v"] * scale)

    prev = None
    for i in sorted(scan.leds):
        e = scan.leds[i]
        if e["status"] != "ok":
            prev = None
            continue
        if prev is not None and prev[0] == i - 1:
            cv2.line(img, prev[1], pt(e), (140, 90, 40), 1, cv2.LINE_AA)
        prev = (i, pt(e))
    r = max(3, round(3 * scale))
    font = cv2.FONT_HERSHEY_SIMPLEX
    for i, e in scan.leds.items():
        if e["status"] == "missing":
            continue
        colour = (60, 220, 60) if e["status"] == "ok" else (0, 150, 255)
        cv2.circle(img, pt(e), r, colour, 1, cv2.LINE_AA)
        if i % 10 == 0:
            x, y = pt(e)
            cv2.putText(img, str(i), (x + r + 2, y - r), font, 0.4, colour, 1, cv2.LINE_AA)
    c = scan.counts()
    title = f"angle {scan.angle:g}: {c['ok']} ok, {c['weak']} weak, {c['missing']} missing"
    cv2.putText(img, title, (10, 24), font, 0.6, (230, 230, 230), 1, cv2.LINE_AA)
    return img
