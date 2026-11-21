"""A tiny headless stand-in for the browser's phone camera, for tests.

Renders the simulated tree's LEDs as coloured dots, seen from a camera walking round
the tree, while the LEDs show the scan code. LEDs on the far side of the trunk are
hidden, like the foliage does in the viewer.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from treemap.scan.code import frame_at, symbol_index


def walk_pose(t: float, height: float, lap_s: float = 12.0, dist: float = 2.2):
    """Camera centre and rotation (rows: right, down, forward in world) at time ``t``."""
    a = 2 * math.pi * t / lap_s + 0.3 * math.sin(t * 0.7)
    d = dist + 0.25 * math.sin(t * 0.9)
    eye = np.array([d * math.sin(a), 1.3 + 0.2 * math.sin(t * 1.3), d * math.cos(a)])
    target = np.array([0.1 * math.sin(t * 2.1), height * 0.5, 0.1 * math.cos(t * 1.7)])
    fwd = target - eye
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0, 1.0, 0])
    right /= np.linalg.norm(right)
    down = np.cross(fwd, right)
    return eye, np.stack([right, down, fwd])


def render(points: np.ndarray, colors: np.ndarray, eye: np.ndarray, R: np.ndarray,
           size=(640, 480), fov_v: float = 55.0, rng: np.random.Generator | None = None,
           occlude: bool = True):
    w, h = size
    f = (h / 2) / math.tan(math.radians(fov_v) / 2)
    X = (points - eye) @ R.T
    img = np.zeros((h, w, 3), np.float32) + 6
    # hidden behind the tree: far side of the trunk, relative to the camera
    cam_dir = np.array([eye[0], 0, eye[2]])
    cam_dir /= np.linalg.norm(cam_dir)
    radial = points * [1, 0, 1]
    facing = (radial @ cam_dir) / np.maximum(np.linalg.norm(radial, axis=1), 1e-6)
    visible = (X[:, 2] > 0.1) & ((facing > -0.35) | (not occlude))
    for p, c in zip(X[visible], colors[visible]):
        u = f * p[0] / p[2] + w / 2 - 0.5
        v = f * p[1] / p[2] + h / 2 - 0.5
        if not (-5 < u < w + 5 and -5 < v < h + 5):
            continue
        s = max(1.2, f * 0.012 / p[2])
        r = int(3 * s) + 1
        x0, x1 = max(int(u) - r, 0), min(int(u) + r + 1, w)
        y0, y1 = max(int(v) - r, 0), min(int(v) + r + 1, h)
        if x0 >= x1 or y0 >= y1:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        g = np.exp(-((xx - u) ** 2 + (yy - v) ** 2) / (2 * s * s))[..., None]
        img[y0:y1, x0:x1] += g * c[::-1].astype(np.float32) * 1.6  # BGR
    if rng is not None:
        img += rng.normal(0, 2.0, img.shape)
    out = np.clip(img, 0, 255).astype(np.uint8)
    ok, jpg = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return cv2.imdecode(jpg, cv2.IMREAD_COLOR), f


def walk_frames(tree, codes, seconds: float, symbol_s: float = 0.15, fps: float = 24.0,
                brightness: int = 160, seed: int = 0, t0: float = 0.0):
    """Yield ``(t, frame)`` while walking; the camera clock is offset from the LEDs'."""
    rng = np.random.default_rng(seed)
    for k in range(int(seconds * fps)):
        t = t0 + k / fps + rng.uniform(-0.004, 0.004)
        eye, R = walk_pose(t, tree.height)
        colors = frame_at(symbol_index(t, symbol_s, codes.shape[1]), codes, brightness)
        img, _ = render(tree.positions, colors, eye, R, rng=rng)
        yield t + 1000.0, img


_rounds: dict = {}


def walk_round(tree, seconds: float = 12.0):
    """A scan round (as :class:`treemap.scan.free.Round`) of one walk, cached per tree."""
    from treemap.scan.code import code_lookup, codewords
    from treemap.scan.free import Round
    from treemap.scan.track import Tracker, decode

    key = (tree.seed, tree.led_count, seconds)
    if key not in _rounds:
        n = tree.led_count
        tracker = Tracker()
        for t, img in walk_frames(tree, codewords(n), seconds):
            tracker.add(t, img)
        f, led, uv = decode(tracker, 0.15, code_lookup(n)).observations(tracker)
        _rounds[key] = Round(f, led, uv, tracker.size, focal=0.8 * 640)
    return _rounds[key]


# -- a flat layout: strips laid on the floor ---------------------------------------------


def flat_layout(n: int = 400, spacing: float = 0.07, seed: int = 0) -> np.ndarray:
    """``(n, 3)`` LED positions on the floor (y = 0): a strip meandering about a
    1.6 x 1.2 m patch, turning back towards the middle near its edges."""
    rng = np.random.default_rng(seed)
    p, heading, turn = np.zeros(2), rng.uniform(0, 2 * math.pi), 0.0
    out = [p.copy()]
    while len(out) < n:
        for attempt in range(60):  # a strip doesn't lie on top of itself: keep 5 cm clear
            t = 0.85 * turn + rng.normal(0, 0.12 + 0.03 * attempt)
            if abs(p[0]) > 0.7 or abs(p[1]) > 0.5:  # steer back in
                t += 0.3 * math.sin(math.atan2(-p[1], -p[0]) - heading)
            q = p + spacing * np.array([math.cos(heading + t), math.sin(heading + t)])
            if len(out) < 4 or np.linalg.norm(np.array(out[:-3]) - q, axis=1).min() > 0.05:
                break
        turn, heading, p = t, heading + t, q
        out.append(p.copy())
    xz = np.array(out)
    return np.column_stack([xz[:, 0], np.zeros(n), xz[:, 1]])


def look_at(eye, target) -> tuple[np.ndarray, np.ndarray]:
    eye, target = np.asarray(eye, float), np.asarray(target, float)
    fwd = target - eye
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0, 1.0, 0])
    right /= np.linalg.norm(right)
    return eye, np.stack([right, np.cross(fwd, right), fwd])


def flat_round(points: np.ndarray, seconds: float = 8.0, moving: bool = False,
               symbol_s: float = 0.15, fps: float = 24.0, seed: int = 0):
    """A scan round of ``points`` filmed by a phone standing at the edge of the layout,
    looking down at it at an angle: held still, or swaying from side to side."""
    from treemap.scan.code import code_lookup, codewords
    from treemap.scan.free import Round
    from treemap.scan.track import Tracker, decode

    rng = np.random.default_rng(seed)
    n = len(points)
    codes = codewords(n)
    tracker = Tracker()
    for k in range(int(seconds * fps)):
        t = k / fps + rng.uniform(-0.004, 0.004)
        sway = 0.35 * math.sin(t * 0.8) if moving else 0.0
        eye, R = look_at([sway, 1.5, 1.3], [0, 0, -0.05])
        colors = frame_at(symbol_index(t, symbol_s, codes.shape[1]), codes, 160)
        img, f = render(points, colors, eye, R, rng=rng, occlude=False)
        tracker.add(t + 1000.0, img)
    obs = decode(tracker, symbol_s, code_lookup(n)).observations(tracker)
    return Round(*obs, tracker.size, focal=f)
