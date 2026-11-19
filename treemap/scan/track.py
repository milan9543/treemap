"""Find the LEDs in each camera frame, follow them from frame to frame, and read the
colour code (:mod:`treemap.scan.code`) each one spells to learn which LED it is.

* :func:`find_blobs`: bright spots in one frame, with their centre and colour symbol.
* :class:`Tracker`: links the blobs of consecutive frames into tracks. The whole picture
  shifts when the camera turns, so each frame's overall shift is measured first (phase
  correlation) and blobs are matched to where their track should be after it.
* :func:`decode`: finds the white sync frames, reads each track's symbols in the slots
  between them, and votes over the cycles a track lived through. Only frame timestamps
  from the camera are used, never the LED player's clock, so stream latency doesn't
  matter.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.spatial import cKDTree

from treemap.scan.code import CODE_LEN, CYCLE, SYNC, repair

MIN_LEVEL = 40.0  # brightness (0-255, brightest channel) a blob must exceed
WHITE_RATIO = 0.55  # weakest/strongest channel above this: white
MAX_MISSES = 3  # frames a track survives without a matching blob
SYNC_SHARE = 0.5  # share of white blobs that makes a frame a sync frame
SLOT_WINDOW = 0.3  # use frames within ±this many symbols of a slot's centre


@dataclass
class Blobs:
    uv: np.ndarray  # (K, 2) px, intensity-weighted centre
    rgb: np.ndarray  # (K, 3) mean colour, 0-255
    sym: np.ndarray  # (K,) 0 red, 1 green, 2 blue, 3 white, -1 unclear
    area: np.ndarray  # (K,) px

    def __len__(self) -> int:
        return len(self.uv)


def classify(rgb: np.ndarray) -> np.ndarray:
    """Colour symbol of each ``(K, 3)`` RGB colour."""
    if not len(rgb):
        return np.zeros(0, dtype=int)
    c = rgb / np.maximum(rgb.max(axis=1, keepdims=True), 1e-6)
    s = np.sort(c, axis=1)
    sym = np.argmax(c, axis=1)
    sym[s[:, 0] > WHITE_RATIO] = SYNC
    sym[(s[:, 0] <= WHITE_RATIO) & (s[:, 1] > 0.75)] = -1  # two strong channels: mixed
    return sym


def find_blobs(img_bgr: np.ndarray, min_level: float = MIN_LEVEL, radius: int = 2) -> Blobs:
    """Local brightness peaks: LEDs close together in the picture glow into each other,
    so they're separated by their peaks, not by dark gaps between them. Each peak's
    position and colour come from the ``(2·radius+1)²`` pixels round it."""
    img = img_bgr.astype(np.float32)
    g = cv2.GaussianBlur(img.max(axis=2), (0, 0), 1.0)
    sample = g[::4, ::4]
    level = float(np.median(sample))
    noise = float(np.median(np.abs(sample - level))) * 1.4826
    thresh = max(min_level, level + 8 * noise)
    peak = (g >= cv2.dilate(g, np.ones((5, 5), np.uint8))) & (g > thresh)
    # a saturated core is a plateau of equal maxima: one peak per plateau
    n, _, stats, cent = cv2.connectedComponentsWithStats(peak.astype(np.uint8), connectivity=8)
    if n <= 1:
        return Blobs(np.zeros((0, 2)), np.zeros((0, 3)), np.zeros(0, int), np.zeros(0, int))
    h, w = g.shape
    px = np.clip(np.round(cent[1:]).astype(int), radius, [w - 1 - radius, h - 1 - radius])
    d = np.arange(-radius, radius + 1)
    yy = px[:, 1, None, None] + d[None, :, None]  # (K, win, 1)
    xx = px[:, 0, None, None] + d[None, None, :]  # (K, 1, win)
    wts = np.maximum(g[yy, xx] - thresh, 0.0)  # (K, win, win)
    tot = wts.sum(axis=(1, 2))
    u = (wts * xx).sum(axis=(1, 2)) / tot
    v = (wts * yy).sum(axis=(1, 2)) / tot
    rgb = (wts[..., None] * img[yy, xx][..., ::-1]).sum(axis=(1, 2)) / tot[:, None]
    area = (wts > 0).sum(axis=(1, 2))
    return Blobs(np.stack([u, v], axis=1), rgb, classify(rgb), area)


@dataclass
class Track:
    id: int
    frames: list[int] = field(default_factory=list)
    uv: list[tuple[float, float]] = field(default_factory=list)
    sym: list[int] = field(default_factory=list)
    vel: np.ndarray = field(default_factory=lambda: np.zeros(2))  # px/frame beyond the global shift
    misses: int = 0

    def predict(self, shift: np.ndarray) -> np.ndarray:
        return np.asarray(self.uv[-1]) + shift * (1 + self.misses) + self.vel


class Tracker:
    """Feed frames in order with :meth:`add`; read the tracks afterwards."""

    def __init__(self) -> None:
        self.times: list[float] = []  # per frame, camera clock (s)
        self.white: list[float] = []  # per frame: share of white blobs (NaN if too few)
        self.tracks: list[Track] = []
        self.active: list[Track] = []
        self.last: tuple[np.ndarray, list[int]] | None = None  # latest frame: blob uv, track ids
        self._prev: np.ndarray | None = None
        self.size: tuple[int, int] | None = None  # w, h

    @property
    def frame_count(self) -> int:
        return len(self.times)

    def add(self, t: float, img_bgr: np.ndarray, blobs: Blobs | None = None) -> Blobs:
        h, w = img_bgr.shape[:2]
        self.size = (w, h)
        blobs = find_blobs(img_bgr) if blobs is None else blobs
        k = len(self.times)
        self.times.append(float(t))
        known = blobs.sym >= 0
        self.white.append(float((blobs.sym[known] == SYNC).mean()) if known.sum() >= 5 else np.nan)

        small = cv2.resize(img_bgr.max(axis=2).astype(np.float32), (w // 2, h // 2),
                           interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), 1.5)
        shift = np.zeros(2)
        if self._prev is not None:
            (dx, dy), response = cv2.phaseCorrelate(self._prev, small)
            if response > 0.05:
                shift = np.array([dx, dy]) * 2
        self._prev = small

        ids = self._match(k, blobs, shift)
        self.last = (blobs.uv, ids)
        return blobs

    def _match(self, k: int, blobs: Blobs, shift: np.ndarray) -> list[int]:
        n = len(blobs)
        assigned: list[int] = [-1] * n
        if n and self.active:
            if n >= 2:
                d, _ = cKDTree(blobs.uv).query(blobs.uv, k=2)
                gate = float(np.clip(0.45 * np.median(d[:, 1]), 3.0, 25.0))
            else:
                gate = 10.0
            pred = np.array([tr.predict(shift) for tr in self.active])
            dist, idx = cKDTree(blobs.uv).query(pred, k=3, distance_upper_bound=gate)
            pairs = sorted(
                (dist[a, j], a, idx[a, j])
                for a in range(len(self.active)) for j in range(3) if np.isfinite(dist[a, j])
            )
            used_t: set[int] = set()
            for _, a, b in pairs:
                if a in used_t or assigned[b] != -1:
                    continue
                used_t.add(a)
                assigned[b] = a
        still: list[Track] = []
        matched = {a for a in assigned if a != -1}
        for a, tr in enumerate(self.active):
            if a not in matched:
                tr.misses += 1
                if tr.misses <= MAX_MISSES:
                    still.append(tr)
        ids = []
        for b in range(n):
            a = assigned[b]
            uv = blobs.uv[b]
            if a == -1:
                tr = Track(id=len(self.tracks))
                self.tracks.append(tr)
            else:
                tr = self.active[a]
                gap = 1 + tr.misses
                resid = (uv - np.asarray(tr.uv[-1])) / gap - shift
                tr.vel = 0.6 * tr.vel + 0.4 * resid
                tr.misses = 0
            tr.frames.append(k)
            tr.uv.append((float(uv[0]), float(uv[1])))
            tr.sym.append(int(blobs.sym[b]))
            still.append(tr)
            ids.append(tr.id)
        self.active = still
        return ids


@dataclass
class Decoded:
    led_of_track: dict[int, int]  # track id -> LED index
    votes: dict[int, int]  # track id -> agreeing cycles
    cycles: int  # sync cycles found

    def observations(self, tracker: Tracker) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(frame, led, uv)`` for every frame of every identified track."""
        f, led, uv = [], [], []
        for tid, i in self.led_of_track.items():
            tr = tracker.tracks[tid]
            f.extend(tr.frames)
            led.extend([i] * len(tr.frames))
            uv.extend(tr.uv)
        return (np.asarray(f, dtype=np.int64), np.asarray(led, dtype=np.int64),
                np.asarray(uv, dtype=float).reshape(-1, 2))


def frame_slots(tracker: Tracker, symbol_s: float) -> tuple[np.ndarray, np.ndarray, int]:
    """Per frame: cycle number and code slot 0..CODE_LEN-1 it reads (-1 if none)."""
    t = np.asarray(tracker.times)
    white = np.nan_to_num(np.asarray(tracker.white), nan=0.0) >= SYNC_SHARE
    cycle = np.full(len(t), -1)
    slot = np.full(len(t), -1)
    # sync runs: consecutive white frames
    centres = []
    k = 0
    while k < len(t):
        if not white[k]:
            k += 1
            continue
        j = k
        while j + 1 < len(t) and white[j + 1]:
            j += 1
        centres.append(float(t[k:j + 1].mean()))
        k = j + 1
    for c, centre in enumerate(centres):
        end = centres[c + 1] - 0.5 * symbol_s if c + 1 < len(centres) else np.inf
        rel = (t - centre) / symbol_s  # in symbols; slot s's centre is at s + 1
        s = np.round(rel).astype(int) - 1
        ok = (s >= 0) & (s < CODE_LEN) & (np.abs(rel - (s + 1)) <= SLOT_WINDOW) & (t < end)
        cycle[ok] = c
        slot[ok] = s[ok]
    return cycle, slot, len(centres)


def decode(tracker: Tracker, symbol_s: float, lookup: dict[tuple[int, ...], int]) -> Decoded:
    cycle, slot, n_cycles = frame_slots(tracker, symbol_s)
    led_of: dict[int, int] = {}
    votes_of: dict[int, int] = {}
    spans: dict[int, tuple[int, int]] = {}
    for tr in tracker.tracks:
        if len(tr.frames) < CODE_LEN:
            continue
        f = np.asarray(tr.frames)
        s = np.asarray(tr.sym)
        c, k = cycle[f], slot[f]
        use = (c >= 0) & (s >= 0) & (s < SYNC)
        if not use.any():
            continue
        cs = np.unique(c[use])
        counts = np.zeros((len(cs), CODE_LEN, 3), dtype=int)
        np.add.at(counts, (np.searchsorted(cs, c[use]), k[use], s[use]), 1)
        votes: Counter[int] = Counter()
        clean: Counter[int] = Counter()
        for row in counts:
            seen = row.sum(axis=1) > 0
            syms = [int(np.argmax(r)) if ok else None for r, ok in zip(row, seen)]
            code = repair(syms)
            if code is None:
                continue
            i = lookup.get(tuple(code))
            if i is None:
                continue
            votes[i] += 1
            if seen.all():
                clean[i] += 1
        if not votes:
            continue
        (best, n), *rest = votes.most_common(2)
        second = rest[0][1] if rest else 0
        if (n >= 2 and n >= 2 * second) or (n == 1 and second == 0 and clean[best] == 1):
            led_of[tr.id] = best
            votes_of[tr.id] = n
            spans[tr.id] = (tr.frames[0], tr.frames[-1])
    # Two tracks at the same time can't both be one LED: keep the better supported one.
    by_led: dict[int, list[int]] = {}
    for tid, i in led_of.items():
        by_led.setdefault(i, []).append(tid)
    for tids in by_led.values():
        if len(tids) < 2:
            continue
        tids.sort(key=lambda t: (votes_of[t], spans[t][1] - spans[t][0]), reverse=True)
        kept: list[int] = []
        for t in tids:
            a, b = spans[t]
            if any(not (b < spans[o][0] or a > spans[o][1]) for o in kept):
                del led_of[t]
                del votes_of[t]
            else:
                kept.append(t)
    return Decoded(led_of, votes_of, n_cycles)
