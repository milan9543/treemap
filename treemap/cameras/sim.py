"""``SimCamera``: synthetic photos of the simulated tree.

Angle convention (shared by the scan and the reconstruction): at view angle θ the
camera stands at ``D · (−sin θ, 0, cos θ)`` at half the tree's height, looking
horizontally at the trunk, so the image's horizontal axis points along world
``(cos θ, 0, sin θ)`` and ``u − c_θ ∝ X cos θ + Z sin θ``. θ = 0 looks from the +Z side;
increasing θ walks clockwise round the tree seen from above (or, keeping the camera
still, turns the tree anticlockwise).

Each photo is a dim, noisy room with the currently lit LEDs drawn as Gaussian blobs in
perspective. To make the scan earn its keep, the camera also mimics a real tree:

* LEDs on the far side shine through foliage and are dimmed; behind the trunk they
  almost vanish;
* each view hides a random few LEDs behind branches;
* each view is a couple of degrees off the requested angle and not quite aimed at the
  trunk, like a tree turned by hand;
* the room has static lights (which the dark reference cancels out), some LEDs throw a
  reflection elsewhere in the picture, and now and then a stray flash appears.

Everything but the per-frame noise and flashes is fixed per (tree seed, angle), so a
rescan of the same view sees the same occlusions.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from treemap.cameras.base import Camera
from treemap.sim.tree import SimTree

GAIN = 600.0  # pixel value of an unobstructed full-white LED's core (clipped to 255)
HALO = (5.0, 0.05)  # glow round each LED: (sigma multiple, relative amplitude)
LED_SIGMA = 1.6  # px blob radius at the camera's standoff distance
GLOW_SHIFT = 0.8  # px, random offset of each LED's apparent centre per view


@dataclass
class _View:
    angle: float
    uv: np.ndarray  # (N, 2) image position of each LED
    sigma: np.ndarray  # (N,) blob size, larger when closer
    visibility: np.ndarray  # (N,) 0-1 after foliage, trunk and random occlusion
    reflect: np.ndarray  # (N,) bool: LED also shows up as a reflection
    reflect_uv: np.ndarray  # (N, 2) where that reflection appears
    background: np.ndarray  # (H, W, 3) float32 room without any LED


class SimCamera(Camera):
    """Renders what a camera at view angle θ would see of the simulated tree.

    ``frame_source`` returns the LED colours currently shown, ``(N, 3)`` uint8 RGB; in
    a sim scan that's the ``SimOutput``'s last frame. ``clean=True`` turns off
    occlusion and false blobs (noise stays) for tests that want an ideal camera.
    """

    def __init__(
        self,
        tree: SimTree,
        frame_source: Callable[[], np.ndarray],
        *,
        width: int = 480,
        height: int = 640,
        fov_deg: float = 60.0,
        noise: float = 2.5,
        clean: bool = False,
        seed: int | None = None,
    ) -> None:
        self.tree = tree
        self.frame_source = frame_source
        self.width, self.height = width, height
        tan = math.tan(math.radians(fov_deg) / 2)
        self.focal = (height / 2) / tan  # px, vertical field of view = fov_deg
        self.distance = tree.height / 2 * 1.15 / tan + tree.radius
        self.eye_height = tree.height / 2
        self.noise = noise
        self.clean = clean
        self.seed = tree.seed if seed is None else seed
        self._rng = np.random.default_rng([self.seed, 0xF00D])  # per-frame noise
        self._view = self._make_view(0.0)

    @property
    def angle(self) -> float:
        return self._view.angle

    def set_angle(self, angle_deg: float) -> bool:
        if float(angle_deg) != self._view.angle:
            self._view = self._make_view(float(angle_deg))
        return True

    def pose(self, angle_deg: float | None = None) -> tuple[float, float, float]:
        """``(actual angle, aim dx, aim dy)`` when asked for ``angle_deg``.

        Like a person turning the tree by hand and re-aiming the phone, the actual
        angle misses by a couple of degrees and the trunk lands up to 15 px off the
        image centre. Fixed per (seed, angle); exact when ``clean``.
        """
        angle = self.angle if angle_deg is None else float(angle_deg)
        if self.clean:
            return angle, 0.0, 0.0
        rng = np.random.default_rng([self.seed, round(angle * 100) % 36000, 7])
        return angle + float(np.clip(rng.normal(0, 2.0), -5, 5)), *rng.uniform(-15, 15, 2)

    def basis(self, angle_deg: float | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(eye, right, forward)`` for the given (default: current) angle."""
        th = math.radians(self.pose(angle_deg)[0])
        right = np.array([math.cos(th), 0.0, math.sin(th)])
        back = np.array([-math.sin(th), 0.0, math.cos(th)])  # trunk -> camera
        eye = back * self.distance + np.array([0.0, self.eye_height, 0.0])
        return eye, right, -back

    def project(self, points: np.ndarray, angle_deg: float | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Pixel positions ``(N, 2)`` and depths ``(N,)`` of world points (metres)."""
        _, du, dv = self.pose(angle_deg)
        eye, right, forward = self.basis(angle_deg)
        rel = np.asarray(points, dtype=np.float64) - eye
        depth = rel @ forward
        u = self.width / 2 + du + self.focal * (rel @ right) / depth
        v = self.height / 2 + dv - self.focal * rel[:, 1] / depth
        return np.stack([u, v], axis=1), depth

    # -- rendering ----------------------------------------------------------------------

    def _make_view(self, angle: float) -> _View:
        tree = self.tree
        pos = tree.positions
        n = len(pos)
        uv, depth = self.project(pos, angle)
        sigma = LED_SIGMA * self.distance / depth
        rng = np.random.default_rng([self.seed, round(angle * 100) % 36000])
        if not self.clean:  # light diffusing through the cap and needles shifts the glow
            uv = uv + rng.normal(0, GLOW_SHIFT, uv.shape)

        _, right, forward = self.basis(angle)
        # -1 = far side of the foliage, 0 = silhouette edge, 1 = nearest the camera
        radius = np.maximum(tree.cone_radius_at(pos[:, 1]), 0.05)
        front = np.clip(-(pos @ forward) / radius, -1.0, 1.0)
        behind = np.clip(-front, 0.0, 1.0)
        visibility = np.ones(n)
        reflect = np.zeros(n, dtype=bool)
        if not self.clean:
            visibility = 1.0 - 0.85 * behind
            lateral = pos @ right
            visibility[(front < 0) & (np.abs(lateral) < tree.trunk_radius * 1.2)] *= 0.03
            hidden = rng.random(n) < 0.05 + 0.4 * behind  # behind a branch in this view
            # about a third vanish completely, the rest glimmer through the needles
            visibility[hidden] *= np.clip(rng.uniform(-0.05, 0.1, hidden.sum()), 0.0, None)
            reflect = rng.random(n) < 0.03
        offset_angle = rng.uniform(0, 2 * np.pi, n)
        offset_len = rng.uniform(15, 60, n)
        reflect_uv = uv + offset_len[:, None] * np.stack(
            [np.cos(offset_angle), np.sin(offset_angle)], axis=1
        )
        return _View(angle, uv, sigma, visibility, reflect, reflect_uv, self._background(rng))

    def _background(self, rng: np.random.Generator) -> np.ndarray:
        """A dark room: uneven ambient light plus a few small static lights."""
        h, w = self.height, self.width
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        gx, gy = rng.uniform(-1, 1, 2)
        ramp = (gx * (xs / w - 0.5) + gy * (ys / h - 0.5)) * 10.0
        bg = np.repeat((12.0 + ramp)[..., None], 3, axis=2)
        bg *= np.array([1.05, 1.0, 0.92], dtype=np.float32)  # slightly warm (BGR)
        if not self.clean:
            for _ in range(rng.integers(2, 5)):  # standby LEDs, a lit window...
                u, v = rng.uniform(0, w), rng.uniform(0, h)
                colour = rng.uniform(80, 255, 3)
                _splat(bg, u, v, rng.uniform(1.5, 4.0), colour)
        return bg

    def _capture(self) -> np.ndarray:
        view = self._view
        colours = np.asarray(self.frame_source())
        if colours.shape != (len(view.uv), 3):
            raise ValueError(
                f"the simulated tree has {len(view.uv)} LEDs but the output shows "
                f"{colours.shape[0]}; regenerate it with `treemap sim new`"
            )
        img = view.background.copy()
        if self.noise > 0:
            img += self._rng.standard_normal(img.shape, dtype=np.float32) * self.noise
        for i in np.flatnonzero(colours.any(axis=1)):
            full = colours[i, ::-1].astype(np.float32) * (GAIN / 255.0)  # RGB -> BGR
            amp = full * view.visibility[i]
            u, v = view.uv[i]
            s = view.sigma[i]
            _splat(img, u, v, s, amp)
            _splat(img, u, v, s * HALO[0], amp * HALO[1])
            if view.reflect[i]:
                ru, rv = view.reflect_uv[i]
                _splat(img, ru, rv, s * 1.5, full * 0.3)
        if not self.clean and self._rng.random() < 0.01:  # a stray flash
            u, v = self._rng.uniform(0, self.width), self._rng.uniform(0, self.height)
            _splat(img, u, v, self._rng.uniform(1.5, 3.0), np.full(3, GAIN * 0.4))
        return np.clip(img, 0, 255).astype(np.uint8)


def _splat(img: np.ndarray, u: float, v: float, sigma: float, amp: np.ndarray) -> None:
    """Add a Gaussian blob centred on pixel coordinates (u, v), in place."""
    h, w = img.shape[:2]
    r = math.ceil(4 * sigma)
    x0, x1 = max(int(u) - r, 0), min(int(u) + r + 2, w)
    y0, y1 = max(int(v) - r, 0), min(int(v) + r + 2, h)
    if x0 >= x1 or y0 >= y1:
        return  # off the picture
    gx = np.exp(-((np.arange(x0, x1) - u) ** 2) / (2 * sigma**2))
    gy = np.exp(-((np.arange(y0, y1) - v) ** 2) / (2 * sigma**2))
    img[y0:y1, x0:x1] += (np.outer(gy, gx)[..., None] * amp).astype(np.float32)
