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
           size=(640, 480), fov_v: float = 55.0, rng: np.random.Generator | None = None):
    w, h = size
    f = (h / 2) / math.tan(math.radians(fov_v) / 2)
    X = (points - eye) @ R.T
    img = np.zeros((h, w, 3), np.float32) + 6
    # hidden behind the tree: far side of the trunk, relative to the camera
    cam_dir = np.array([eye[0], 0, eye[2]])
    cam_dir /= np.linalg.norm(cam_dir)
    radial = points * [1, 0, 1]
    facing = (radial @ cam_dir) / np.maximum(np.linalg.norm(radial, axis=1), 1e-6)
    visible = (X[:, 2] > 0.1) & (facing > -0.35)
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
