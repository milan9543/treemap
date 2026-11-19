"""3D LED positions from a free-moving camera (structure from motion).

The decoded tracks give, for many frames, which LED is at which pixel. Nothing is
known about where the camera was, so the camera poses are solved together with the
LED positions:

1. **Keyframes**: frames where the picture has moved on enough from the previous one.
2. **Start**: the keyframe pair that sees the most LEDs from the most different
   viewpoints. Its essential matrix gives the relative pose, and triangulation gives
   the first LED positions.
3. **Grow**: register further keyframes against the known LEDs (PnP with RANSAC),
   triangulate the LEDs they add, and bundle-adjust from time to time.
4. **Bundle adjustment**: Cauchy-robust least squares over all poses, LED positions and
   the focal length.
5. **Up**: a hand-held phone (or the sim's walking camera) keeps its horizon roughly
   level, so world up is the direction perpendicular to every camera's right vector.

Camera model: pinhole, principal point at the image centre, no distortion. OpenCV axes
(x right, y down, z forward). The result's scale and heading are arbitrary;
:func:`treemap.scan.cleanup.normalise` sets the scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix

MIN_PNP = 12  # known LEDs a keyframe must see to be registered
MIN_INIT = 30  # LEDs a starting pair must share
MIN_VIEWS = 3  # inlier views for an LED to count as measured
MIN_SPREAD_DEG = 15.0  # and the angle its views span
MAX_REPROJ = 4.0  # px, inlier threshold


class SfmError(RuntimeError):
    """Not enough data to solve."""


@dataclass
class SfmResult:
    positions: np.ndarray  # (N, 3) y up, NaN where not measured
    measured: np.ndarray  # (N,) bool
    views: np.ndarray  # (N,) inlier keyframe views per LED
    spread_deg: np.ndarray  # (N,) angle spanned by those views
    focal: float  # px
    keyframes: np.ndarray  # frame ids registered
    centres: np.ndarray  # (K, 3) camera centres, same frame as positions
    info: dict = field(default_factory=dict)


# -- geometry ------------------------------------------------------------------------


def rotate(points: np.ndarray, rvecs: np.ndarray) -> np.ndarray:
    """Rotate each point by its own Rodrigues vector (both (M, 3))."""
    theta = np.linalg.norm(rvecs, axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(theta > 1e-12, rvecs / theta, 0.0)
    cos, sin = np.cos(theta), np.sin(theta)
    dot = (k * points).sum(axis=1, keepdims=True)
    return points * cos + np.cross(k, points) * sin + k * dot * (1 - cos)


def project(points: np.ndarray, rvecs: np.ndarray, tvecs: np.ndarray, f: float,
            c: np.ndarray) -> np.ndarray:
    X = rotate(points, rvecs) + tvecs
    z = np.where(np.abs(X[:, 2]) < 1e-9, 1e-9, X[:, 2])
    return f * X[:, :2] / z[:, None] + c


def _K(f: float, c: np.ndarray) -> np.ndarray:
    return np.array([[f, 0, c[0]], [0, f, c[1]], [0, 0, 1.0]])


def _pose_matrix(rvec: np.ndarray, tvec: np.ndarray) -> np.ndarray:
    R, _ = cv2.Rodrigues(np.asarray(rvec, dtype=float))
    return np.hstack([R, np.asarray(tvec, dtype=float).reshape(3, 1)])


def _centre(rvec: np.ndarray, tvec: np.ndarray) -> np.ndarray:
    R, _ = cv2.Rodrigues(np.asarray(rvec, dtype=float))
    return -R.T @ np.asarray(tvec, dtype=float)


def triangulate(rays: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    """Linear (DLT) triangulation from ``(3x4 normalised pose, normalised xy)`` pairs."""
    A = []
    for P, (x, y) in rays:
        A.append(x * P[2] - P[0])
        A.append(y * P[2] - P[1])
    _, _, vt = np.linalg.svd(np.asarray(A))
    X = vt[-1]
    return X[:3] / X[3] if abs(X[3]) > 1e-12 else np.full(3, np.nan)


# -- the solver ----------------------------------------------------------------------


class _Problem:
    def __init__(self, frame: np.ndarray, led: np.ndarray, uv: np.ndarray, size: tuple[int, int],
                 f0: float, led_count: int, max_keyframes: int) -> None:
        self.c = np.array([size[0] / 2 - 0.5, size[1] / 2 - 0.5])
        self.f = float(f0)
        self.n = led_count
        self.min_disp = 0.012 * max(size)
        order = np.lexsort((led, frame))
        frame, led, uv = frame[order], led[order], uv[order]
        ids, start = np.unique(frame, return_index=True)
        stops = np.append(start[1:], len(frame))
        self.views: dict[int, tuple[np.ndarray, np.ndarray]] = {}  # frame -> (led, uv)
        for fid, a, b in zip(ids, start, stops):
            if b - a >= MIN_PNP:
                leds, first = np.unique(led[a:b], return_index=True)  # one blob per LED
                self.views[int(fid)] = (leds, uv[a:b][first])
        self.keyframes = self._pick_keyframes(max_keyframes)
        self.pose: dict[int, tuple[np.ndarray, np.ndarray]] = {}  # keyframe -> rvec, tvec
        self.points: dict[int, np.ndarray] = {}

    def _pick_keyframes(self, cap: int) -> list[int]:
        kf: list[int] = []
        last = None
        for fid in sorted(self.views):
            leds, uv = self.views[fid]
            if last is None:
                kf.append(fid)
                last = (leds, uv)
                continue
            common, ia, ib = np.intersect1d(last[0], leds, return_indices=True)
            moved = (np.median(np.linalg.norm(last[1][ia] - uv[ib], axis=1))
                     if len(common) else np.inf)
            if moved >= self.min_disp or len(common) < 0.6 * len(last[0]):
                kf.append(fid)
                last = (leds, uv)
        if len(kf) > cap:
            kf = [kf[i] for i in np.round(np.linspace(0, len(kf) - 1, cap)).astype(int)]
        return kf

    def _norm(self, uv: np.ndarray) -> np.ndarray:
        return (uv - self.c) / self.f

    # -- start -----------------------------------------------------------------------

    def initialise(self) -> None:
        kf = self.keyframes
        best = None
        for i in range(len(kf)):
            for d in (3, 6, 12, 24, 48):
                if i + d >= len(kf):
                    break
                r = self._try_pair(kf[i], kf[i + d])
                if r is not None and (best is None or r[0] > best[0]):
                    best = r
        if best is None:
            raise SfmError(
                "no two views share enough LEDs from different enough places; walk round "
                "the tree rather than turning on the spot"
            )
        _, a, b, R, t, pts = best
        self.pose[a] = (np.zeros(3), np.zeros(3))
        self.pose[b] = (cv2.Rodrigues(R)[0].ravel(), t.ravel())
        self.points.update(pts)

    def _try_pair(self, a: int, b: int):
        la, ua = self.views[a]
        lb, ub = self.views[b]
        common, ia, ib = np.intersect1d(la, lb, return_indices=True)
        if len(common) < MIN_INIT:
            return None
        pa, pb = ua[ia], ub[ib]
        K = _K(self.f, self.c)
        E, mask = cv2.findEssentialMat(pa, pb, K, method=cv2.RANSAC, prob=0.999, threshold=1.5)
        if E is None or E.shape != (3, 3):
            return None
        n_in, R, t, mask = cv2.recoverPose(E, pa, pb, K, mask=mask)
        if n_in < MIN_INIT:
            return None
        keep = mask.ravel() > 0
        P0 = np.hstack([np.eye(3), np.zeros((3, 1))])
        P1 = np.hstack([R, t])
        X = cv2.triangulatePoints(P0, P1, self._norm(pa[keep]).T, self._norm(pb[keep]).T)
        X = (X[:3] / X[3]).T
        c1 = -R.T @ t.ravel()
        ra = X / np.linalg.norm(X, axis=1, keepdims=True)
        rb = (X - c1) / np.linalg.norm(X - c1, axis=1, keepdims=True)
        ang = np.degrees(np.arccos(np.clip((ra * rb).sum(axis=1), -1, 1)))
        z1 = (X @ R.T + t.ravel())[:, 2]
        good = (X[:, 2] > 0) & (z1 > 0) & (ang > 1.0)
        if good.sum() < MIN_INIT:
            return None
        score = good.sum() * min(float(np.median(ang[good])), 8.0)
        pts = {int(i): x for i, x, g in zip(common[keep], X, good) if g}
        return score, a, b, R, t, pts

    # -- grow ------------------------------------------------------------------------

    def grow(self) -> None:
        failed: set[int] = set()
        since_ba = 0
        while True:
            best, best_n = None, MIN_PNP - 1
            for fid in self.keyframes:
                if fid in self.pose or fid in failed:
                    continue
                n = sum(1 for i in self.views[fid][0] if int(i) in self.points)
                if n > best_n:
                    best, best_n = fid, n
            if best is None:
                break
            if not self._register(best):
                failed.add(best)
                continue
            failed.clear()  # new points may let earlier failures register now
            self._triangulate_new()
            since_ba += 1
            if since_ba >= max(10, len(self.pose) // 4):
                self.bundle_adjust(max_nfev=20)
                since_ba = 0

    def _register(self, fid: int) -> bool:
        leds, uv = self.views[fid]
        have = np.array([int(i) in self.points for i in leds])
        obj = np.array([self.points[int(i)] for i in leds[have]])
        img = uv[have]
        ok, rvec, tvec, inl = cv2.solvePnPRansac(
            obj, img, _K(self.f, self.c), None, reprojectionError=MAX_REPROJ,
            iterationsCount=200, confidence=0.999, flags=cv2.SOLVEPNP_EPNP,
        )
        if not ok or inl is None or len(inl) < MIN_PNP:
            return False
        rvec, tvec = cv2.solvePnPRefineLM(obj[inl.ravel()], img[inl.ravel()],
                                          _K(self.f, self.c), None, rvec, tvec)
        self.pose[fid] = (rvec.ravel(), tvec.ravel())
        return True

    def _triangulate_new(self, recheck: bool = False) -> None:
        seen: dict[int, list[tuple[int, np.ndarray]]] = {}
        for fid in self.pose:
            leds, uv = self.views[fid]
            for i, p in zip(leds, uv):
                i = int(i)
                if recheck or i not in self.points:
                    seen.setdefault(i, []).append((fid, p))
        mats = {fid: _pose_matrix(*self.pose[fid]) for fid in self.pose}
        centres = {fid: _centre(*self.pose[fid]) for fid in self.pose}
        for i, obs in seen.items():
            if len(obs) < 2:
                continue
            X = triangulate([(mats[f], self._norm(p)) for f, p in obs])
            if not np.isfinite(X).all():
                continue
            good = 0
            dirs = []
            for f, p in obs:
                x = mats[f] @ np.append(X, 1)
                if x[2] <= 0:
                    continue
                err = np.linalg.norm(self.f * x[:2] / x[2] + self.c - p)
                if err < MAX_REPROJ:
                    good += 1
                    d = X - centres[f]
                    dirs.append(d / np.linalg.norm(d))
            if good >= 2 and _spread_deg(np.array(dirs)) > 2.0:
                self.points[i] = X

    # -- bundle adjustment -------------------------------------------------------------

    def _ba_data(self):
        cams = sorted(self.pose)
        pts = sorted(self.points)
        ci = {f: k for k, f in enumerate(cams)}
        pi = {i: k for k, i in enumerate(pts)}
        cam_idx, pt_idx, uv = [], [], []
        for f in cams:
            leds, p = self.views[f]
            for i, q in zip(leds, p):
                k = pi.get(int(i))
                if k is not None:
                    cam_idx.append(ci[f])
                    pt_idx.append(k)
                    uv.append(q)
        return cams, pts, np.array(cam_idx), np.array(pt_idx), np.array(uv).reshape(-1, 2)

    def bundle_adjust(self, max_nfev: int = 60, f_scale: float = 2.0) -> np.ndarray:
        """Refine everything; returns each observation's residual (px) for _ba_data."""
        cams, pts, cam_idx, pt_idx, uv = self._ba_data()
        nc, npt = len(cams), len(pts)
        x0 = np.concatenate([
            [self.f],
            np.concatenate([np.concatenate(self.pose[f]) for f in cams]),
            np.concatenate([self.points[i] for i in pts]),
        ])

        def unpack(x):
            return x[0], x[1:1 + 6 * nc].reshape(nc, 6), x[1 + 6 * nc:].reshape(npt, 3)

        def fun(x):
            f, cp, P = unpack(x)
            return (project(P[pt_idx], cp[cam_idx, :3], cp[cam_idx, 3:], f, self.c) - uv).ravel()

        m = len(uv)
        A = lil_matrix((2 * m, len(x0)), dtype=int)
        rows = np.arange(m)
        A[:, 0] = 1
        for k in range(6):
            A[2 * rows, 1 + 6 * cam_idx + k] = 1
            A[2 * rows + 1, 1 + 6 * cam_idx + k] = 1
        for k in range(3):
            A[2 * rows, 1 + 6 * nc + 3 * pt_idx + k] = 1
            A[2 * rows + 1, 1 + 6 * nc + 3 * pt_idx + k] = 1
        res = least_squares(fun, x0, jac_sparsity=A, x_scale="jac", loss="cauchy",
                            f_scale=f_scale, method="trf", max_nfev=max_nfev, ftol=1e-6)
        f, cp, P = unpack(res.x)
        self.f = float(f)
        for k, fid in enumerate(cams):
            self.pose[fid] = (cp[k, :3].copy(), cp[k, 3:].copy())
        for k, i in enumerate(pts):
            self.points[i] = P[k].copy()
        return np.linalg.norm(res.fun.reshape(-1, 2), axis=1)

    def drop_outliers(self, resid: np.ndarray) -> int:
        """Forget LED positions most of whose observations disagree with the model."""
        cams, pts, cam_idx, pt_idx, _ = self._ba_data()
        bad = resid > MAX_REPROJ
        dropped = 0
        for k, i in enumerate(pts):
            sel = pt_idx == k
            if (~bad[sel]).sum() < 2:
                del self.points[i]
                dropped += 1
        return dropped


def _spread_deg(dirs: np.ndarray) -> float:
    """Widest angle between any two of the unit vectors ``dirs`` (approximately)."""
    if len(dirs) < 2:
        return 0.0
    mean = dirs.mean(axis=0)
    if np.linalg.norm(mean) < 1e-9:
        return 180.0
    mean /= np.linalg.norm(mean)
    a = dirs[np.argmax(np.arccos(np.clip(dirs @ mean, -1, 1)))]
    return float(np.degrees(np.arccos(np.clip(dirs @ a, -1, 1)).max()))


def _up_rotation(rvecs: list[np.ndarray]) -> np.ndarray:
    """Rotation taking the solved frame to one with +y up (see the module docstring)."""
    Rs = [cv2.Rodrigues(np.asarray(r, dtype=float))[0] for r in rvecs]
    rights = np.array([R[0] for R in Rs])  # camera x axis in world coordinates
    ups = np.array([-R[1] for R in Rs])  # camera up (−y) in world coordinates
    mean_up = ups.mean(axis=0)
    mean_up /= np.linalg.norm(mean_up)
    w, v = np.linalg.eigh(rights.T @ rights)
    up = v[:, 0] if w[1] > 0.05 * len(Rs) else mean_up  # needs some spread of headings
    if up @ mean_up < 0:
        up = -up
    y = up / np.linalg.norm(up)
    x = rights.mean(axis=0) - (rights.mean(axis=0) @ y) * y
    if np.linalg.norm(x) < 1e-6:
        x = np.cross(y, [0, 0, 1.0]) if abs(y[2]) < 0.9 else np.cross(y, [1.0, 0, 0])
    x /= np.linalg.norm(x)
    z = np.cross(x, y)
    return np.stack([x, y, z])  # rows: new axes in old coordinates


def solve(frame: np.ndarray, led: np.ndarray, uv: np.ndarray, size: tuple[int, int],
          f0: float, led_count: int, max_keyframes: int = 150) -> SfmResult:
    """Solve camera poses and LED positions from ``(frame id, LED, pixel)`` observations."""
    if len(frame) == 0:
        raise SfmError("no LEDs were identified")
    pr = _Problem(np.asarray(frame), np.asarray(led), np.asarray(uv, dtype=float), size, f0,
                  led_count, max_keyframes)
    if len(pr.keyframes) < 2:
        raise SfmError("the camera saw too little; walk round the tree while scanning")
    pr.initialise()
    pr.bundle_adjust(max_nfev=30)
    pr.grow()
    resid = pr.bundle_adjust()
    if pr.drop_outliers(resid):
        resid = pr.bundle_adjust()
    pr._triangulate_new()  # LEDs that the refined poses now place well
    resid = pr.bundle_adjust()

    cams, pts, cam_idx, pt_idx, _ = pr._ba_data()
    centres = np.array([_centre(*pr.pose[f]) for f in cams])
    inlier = resid < max(MAX_REPROJ, 3 * 1.4826 * float(np.median(resid)))
    R_up = _up_rotation([pr.pose[f][0] for f in cams])

    n = led_count
    positions = np.full((n, 3), np.nan)
    views = np.zeros(n, dtype=int)
    spread = np.zeros(n)
    for k, i in enumerate(pts):
        sel = (pt_idx == k) & inlier
        X = pr.points[i]
        dirs = X - centres[cam_idx[sel]]
        dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
        views[i] = int(sel.sum())
        spread[i] = _spread_deg(dirs)
        positions[i] = R_up @ X
    measured = (views >= MIN_VIEWS) & (spread >= MIN_SPREAD_DEG)
    positions[~measured] = np.nan
    info = {
        "keyframes": len(pr.keyframes),
        "registered": len(cams),
        "median_residual_px": round(float(np.median(resid)), 3) if len(resid) else None,
        "focal_px": round(pr.f, 1),
    }
    return SfmResult(positions, measured, views, spread, pr.f, np.array(cams),
                     centres @ R_up.T, info)
