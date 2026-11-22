"""Free-moving scan: walk round the tree with the camera while every LED flashes its code.

A scan runs in rounds:

1. **flashing** (``round_s``): the LEDs spell their codes (:mod:`treemap.scan.code`)
   while each camera frame is tracked and decoded (:mod:`treemap.scan.track`);
2. **solving**: the observations of *all* rounds so far are solved for 3D positions
   (:mod:`treemap.scan.sfm`), cleaned up along the strips and saved as the tree map;
3. **status** (``status_s``, or until ``next_round`` says go): the tree shows the
   result: green ok, yellow interpolated, red failed. Walk to where it's red; the next
   round fills it in.

Each round's observations are saved to ``<scan_dir>/round_XX.npz``, so later rounds,
``treemap reconstruct`` and a scan resumed another day all build on them.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from treemap.cameras.base import Camera
from treemap.mapping.model import TreeMap
from treemap.mapping.quality import STATUS_COLORS, status_frame
from treemap.outputs.base import LedOutput
from treemap.scan import planar, sfm
from treemap.scan.cleanup import cleanup, normalise
from treemap.scan.code import code_lookup, codewords, frame_at, symbol_index
from treemap.scan.colours import ColourModel
from treemap.scan.track import Decoded, Tracker, decode

FRAME_STRIDE = 1_000_000  # frame ids: round * FRAME_STRIDE + frame in round
OVERRIDES_FILE = "overrides.json"
UPDATE_S = 0.25  # how often progress and detections are reported while flashing


class ScanError(RuntimeError):
    """The scan can't go on (e.g. rounds from a different camera)."""


# -- saved rounds -----------------------------------------------------------------------


@dataclass
class Round:
    frame: np.ndarray  # (M,) frame number within the round
    led: np.ndarray  # (M,)
    uv: np.ndarray  # (M, 2) px
    size: tuple[int, int]  # image width, height
    focal: float  # px, starting guess for this camera
    meta: dict[str, Any] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.stem + ".tmp.npz")
        np.savez_compressed(tmp, frame=self.frame, led=self.led, uv=self.uv,
                            size=np.array(self.size), focal=np.array(self.focal),
                            meta=np.array(json.dumps(self.meta)))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Round:
        with np.load(path) as z:
            return cls(z["frame"], z["led"], z["uv"], tuple(int(v) for v in z["size"]),
                       float(z["focal"]), json.loads(str(z["meta"])))


def round_paths(scan_dir: Path) -> list[Path]:
    return sorted(p for p in scan_dir.glob("round_*.npz") if ".tmp" not in p.name)


def load_rounds(scan_dir: Path) -> list[Round]:
    return [Round.load(p) for p in round_paths(scan_dir)]


def clear_rounds(scan_dir: Path) -> None:
    for p in round_paths(scan_dir):
        p.unlink()


def load_overrides(scan_dir: Path) -> set[int]:
    """LEDs marked (with ``treemap fix``) to be interpolated instead of measured."""
    path = scan_dir / OVERRIDES_FILE
    if not path.exists():
        return set()
    return {int(i) for i in json.loads(path.read_text()).get("interpolate", [])}


def save_overrides(scan_dir: Path, interpolate: set[int]) -> None:
    scan_dir.mkdir(parents=True, exist_ok=True)
    (scan_dir / OVERRIDES_FILE).write_text(json.dumps({"interpolate": sorted(interpolate)}))


# -- solving ----------------------------------------------------------------------------


# Waits, calling check_cancel, until the user is ready for the round after ``round``;
# returns True to go on, False to finish the scan there.
NextRound = Callable[[int, Callable[[], None]], bool]


def read_frame(n: int, read: set[int]) -> np.ndarray:
    """Before there's a map: LEDs read so far in the interpolated colour (found, not yet
    placed), the rest in the failed colour."""
    frame = np.tile(np.array(STATUS_COLORS["failed"], np.uint8), (n, 1))
    frame[sorted(i for i in read if 0 <= i < n)] = STATUS_COLORS["interpolated"]
    return frame


def build_map(rounds: list[Round], led_count: int, interpolate: set[int] = frozenset(),
              shape: str = "tree") -> tuple[TreeMap, sfm.SfmResult]:
    """All rounds' observations -> positions -> cleanup -> normalised :class:`TreeMap`.

    ``shape`` "tree" solves 3D positions (:mod:`treemap.scan.sfm`), "flat" 2D ones on a
    plane (:mod:`treemap.scan.planar`). LEDs in ``interpolate`` ignore their observations
    and are filled from neighbours.
    Raises :class:`sfm.SfmError` if there isn't enough to solve.
    """
    rounds = [r for r in rounds if len(r.frame)]
    if not rounds:
        raise sfm.SfmError("no rounds with identified LEDs yet; scan first")
    sizes = {r.size for r in rounds}
    if len(sizes) > 1:
        raise ScanError(f"the rounds were filmed at different sizes {sorted(sizes)}; "
                        "scan again")
    frame = np.concatenate([k * FRAME_STRIDE + r.frame for k, r in enumerate(rounds)])
    led = np.concatenate([r.led for r in rounds])
    uv = np.concatenate([r.uv for r in rounds])
    if interpolate:
        keep = ~np.isin(led, sorted(interpolate))
        frame, led, uv = frame[keep], led[keep], uv[keep]
    if led.max(initial=-1) >= led_count:
        raise ScanError(f"the rounds have LEDs beyond the tree's {led_count}; "
                        "scan again")
    solver = planar.solve if shape == "flat" else sfm.solve
    res = solver(frame, led, uv, rounds[0].size, float(np.median([r.focal for r in rounds])),
                 led_count)
    try:
        P, status, info = cleanup(res.positions)
        P = normalise(P, status)
    except ValueError as e:
        raise sfm.SfmError(str(e)) from None
    meta = {
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rounds": len(rounds),
        "shape": shape,
        **res.info,
        "outliers": info["outliers"],
        "forced_interpolate": sorted(interpolate),
        "views": res.views.tolist(),
    }
    return TreeMap(P, status, meta), res


# -- scanning ---------------------------------------------------------------------------


def focal_guess(size: tuple[int, int], meta: dict, fov_h_deg: float) -> float:
    """Focal length in px: from the frame's vertical FOV if the camera says, else from
    the configured horizontal FOV."""
    w, h = size
    if isinstance(meta.get("fov_v"), (int, float)) and 1 < meta["fov_v"] < 170:
        return (h / 2) / math.tan(math.radians(meta["fov_v"]) / 2)
    return (w / 2) / math.tan(math.radians(fov_h_deg) / 2)


@dataclass
class ScanSettings:
    led_count: int
    scan_dir: Path
    map_path: Path
    symbol_s: float = 0.15
    brightness: int = 160
    round_s: float = 12.0
    status_s: float = 4.0
    max_rounds: int = 10
    fov_deg: float = 65.0
    colours: ColourModel | None = None  # the camera's measured colours; None: thresholds
    shape: str = "tree"  # tree: 3D solve; flat: 2D (see build_map)


def detections(tracker: Tracker, decoded: Decoded | None) -> dict:
    """The latest frame's blobs for the phone inset: ``[u, v, led or -1]``."""
    if not tracker.last or tracker.size is None:
        return {"size": [0, 0], "blobs": []}
    uv, ids = tracker.last
    known = decoded.led_of_track if decoded else {}
    return {
        "size": list(tracker.size),
        "blobs": [[round(float(u), 1), round(float(v), 1), known.get(t, -1)]
                  for (u, v), t in zip(uv, ids)],
    }


class CodePlayer:
    """Shows the code on the LEDs, each symbol on time, from a thread of its own: the
    scan's frame processing takes long enough on a real camera's frames to make the
    symbols late (and the codes unreadable) if the same loop played them."""

    def __init__(self, output: LedOutput, codes: np.ndarray, symbol_s: float,
                 brightness: int) -> None:
        self.output, self.codes, self.symbol_s, self.brightness = output, codes, symbol_s, brightness
        self.start = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="scan-code", daemon=True)

    def _run(self) -> None:
        k = 0  # symbols shown so far
        while not self._stop.is_set():
            slot = symbol_index(k * self.symbol_s + 1e-6, self.symbol_s, self.codes.shape[1])
            self.output.show(frame_at(slot, self.codes, self.brightness))
            k += 1
            self._stop.wait(max(self.start + k * self.symbol_s - time.monotonic(), 0.0))

    def __enter__(self) -> CodePlayer:
        self.start = time.monotonic()
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()


def scan(
    output: LedOutput,
    camera: Camera,
    s: ScanSettings,
    *,
    fresh: bool = False,
    rounds: int | None = None,
    on_update: Callable[[dict], None] = lambda u: None,
    check_cancel: Callable[[], None] = lambda: None,
    sleep: Callable[[float], None] = time.sleep,
    next_round: NextRound | None = None,
) -> TreeMap | None:
    """Run scan rounds until every LED is ok, ``rounds`` (default ``s.max_rounds``) have
    run, or ``check_cancel`` raises. Returns the latest map (None if none could be
    solved). ``on_update`` gets progress dicts (round, phase, seconds left, counts...).

    With ``next_round``, the status between rounds stays on the LEDs (progress
    ``waiting``) until ``next_round(round, check_cancel)`` returns: True to go on, False
    to finish here."""
    n = s.led_count
    codes, lookup = codewords(n), code_lookup(n)
    if fresh:
        clear_rounds(s.scan_dir)
    saved = load_rounds(s.scan_dir)
    tree_map: TreeMap | None = None
    dim = np.full((n, 3), max(s.brightness // 6, 4), dtype=np.uint8)

    last_round = len(saved) + (rounds or s.max_rounds) - 1
    for k in range(len(saved), last_round + 1):
        base = {"round": k + 1, "rounds_saved": len(saved)}
        # 1. flashing
        tracker = Tracker(s.colours.classify) if s.colours is not None else Tracker()
        decoded: Decoded | None = None
        meta: dict = {}
        camera.drain()
        last_update = 0.0
        with CodePlayer(output, codes, s.symbol_s, s.brightness) as player:
            start = player.start
            while (now := time.monotonic()) < start + s.round_s:
                check_cancel()
                frame = camera.read(timeout=0.05)
                if frame is not None:
                    tracker.add(frame.t, frame.image)
                    meta = frame.meta
                if now - last_update >= UPDATE_S:
                    last_update = now
                    decoded = decode(tracker, s.symbol_s, lookup)
                    camera.show_detections(detections(tracker, decoded))
                    on_update({**base, "phase": "flashing",
                               "remaining": round(start + s.round_s - now, 1),
                               "frames": tracker.frame_count,
                               "identified": len(set(decoded.led_of_track.values()))})
        # 2. solving
        output.show(dim)
        decoded = decode(tracker, s.symbol_s, lookup)
        identified = len(set(decoded.led_of_track.values()))
        on_update({**base, "phase": "solving", "frames": tracker.frame_count,
                   "identified": identified})
        if tracker.size is None:
            raise ScanError("no camera frames arrived: is the viewer open and showing the tree?")
        f, led, uv = decoded.observations(tracker)
        if len(f):
            rnd = Round(f, led, uv, tracker.size, focal_guess(tracker.size, meta, s.fov_deg),
                        {"frames": tracker.frame_count, "identified": identified,
                         "cycles": decoded.cycles})
            rnd.save(s.scan_dir / f"round_{k + 1:02d}.npz")
            saved.append(rnd)
        message = ""
        try:
            tree_map, res = build_map(saved, n, load_overrides(s.scan_dir), s.shape)
            tree_map.save(s.map_path)
        except (sfm.SfmError, ScanError) as e:
            message = str(e)
        # 3. status
        counts = tree_map.counts() if tree_map is not None else None
        on_update({**base, "rounds_saved": len(saved), "phase": "status",
                   "remaining": s.status_s, "frames": tracker.frame_count,
                   "identified": identified, "counts": counts, "message": message})
        if tree_map is not None:
            output.show(status_frame(tree_map))
        else:  # too few to place: LEDs read so far yellow, the rest red
            output.show(read_frame(n, {int(i) for r in saved for i in r.led}))
        finished = bool(counts and counts["ok"] == n)
        if next_round is not None and not finished and k < last_round:
            on_update({**base, "rounds_saved": len(saved), "phase": "status", "remaining": None,
                       "waiting": True, "frames": tracker.frame_count, "identified": identified,
                       "counts": counts, "message": message})
            if not next_round(k + 1, check_cancel):
                break
            continue
        end = time.monotonic() + s.status_s
        while time.monotonic() < end:
            check_cancel()
            sleep(min(0.1, max(end - time.monotonic(), 0)))
        if finished:
            break
    return tree_map
