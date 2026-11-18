"""3D positions from the per-angle 2D detections.

Camera model (see :mod:`treemap.cameras.sim` for the angle convention): at view angle
φ = θ + δθ the camera sits on a circle round the trunk axis at distance 1 (the unit of
length here) and eye height 0, so for a point P

    d = 1 − P·b,   u = cx + f · (P·r) / d,   v = cy − f · P_y / d

with right vector ``r = (cos φ, 0, sin φ)`` and ``b = (−sin φ, 0, cos φ)`` pointing
from the trunk to the camera. Unknowns: the focal length ``f`` (px) shared by all views,
and per view the image position of the axis (``cx``, ``cy``, which also absorb a camera
that isn't aimed exactly at the trunk or is slightly tilted) and a small angle error
``δθ`` (``δθ = 0`` for the first view, which fixes the orientation).

Solving it:

1. **Weak perspective** start: ``u − cx = s·(X cos θ + Z sin θ)``, ``cy − v = s·Y``,
   solved by alternating confidence-weighted least squares (points, then per-view
   offsets), with robust weights so reflections don't drag LEDs about.
2. **Perspective refinement**: Levenberg-Marquardt on the reprojection error over all
   LEDs and camera parameters jointly, with iteratively re-weighted (Cauchy) residuals.
   The weak model's front/back scale error is up to ±25% at typical distances, which
   matters for LEDs not seen from both sides.

Only ``ok`` detections are used. An LED gets a position if, after down-weighting
outliers, it was seen from at least two views far enough apart (≳35°) to fix its depth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from treemap.mapping.model import TreeMap
from treemap.scan.capture import AngleScan
from treemap.scan.cleanup import cleanup, normalise

MIN_SPREAD = 0.1  # min/max eigenvalue of a point's lateral normal matrix (~35° between views)
DEFAULT_FOCAL = 0.8  # initial focal length as a fraction of the image's long side (~64° FOV)
MIN_SCALE_PX = 1.0  # robust residual scale never tighter than this (centroid noise, real lenses)
INLIER_SCALES = 3.0  # a detection within this many robust scales of the model is an inlier


class ReconstructionError(RuntimeError):
    """Not enough data to reconstruct."""


@dataclass
class Observations:
    led: np.ndarray  # (M,) LED index of each detection
    view: np.ndarray  # (M,) view index
    uv: np.ndarray  # (M, 2) px
    conf: np.ndarray  # (M,) detection confidence
    angles: np.ndarray  # (V,) degrees
    sizes: np.ndarray  # (V, 2) image width, height
    led_count: int

    @classmethod
    def from_scans(cls, scans: list[AngleScan], led_count: int) -> Observations:
        led, view, uv, conf = [], [], [], []
        for k, s in enumerate(scans):
            if s.led_count != led_count:
                raise ReconstructionError(
                    f"angle {s.angle:g} was scanned with {s.led_count} LEDs, not {led_count}"
                )
            for i in s.ok_indices():
                e = s.leds[i]
                led.append(i)
                view.append(k)
                uv.append((e["u"], e["v"]))
                conf.append(e["confidence"])
        return cls(
            led=np.asarray(led, dtype=int),
            view=np.asarray(view, dtype=int),
            uv=np.asarray(uv, dtype=float).reshape(-1, 2),
            conf=np.asarray(conf, dtype=float),
            angles=np.array([s.angle for s in scans], dtype=float),
            sizes=np.array([s.image_size for s in scans], dtype=float).reshape(-1, 2),
            led_count=led_count,
        )


@dataclass
class Reconstruction:
    positions: np.ndarray  # (N, 3), NaN where not measured; unit = camera distance
    measured: np.ndarray  # (N,) bool
    views: np.ndarray  # (N,) inlier views per LED
    residual: np.ndarray  # (N,) RMS reprojection error of the inlier views, px
    focal: float  # px
    angle_offsets: np.ndarray  # (V,) δθ, degrees
    centers: np.ndarray  # (V, 2) image position of the trunk axis (cx, cy)
    info: dict = field(default_factory=dict)


def build_map(scans: list[AngleScan], led_count: int) -> tuple[TreeMap, Reconstruction]:
    """Scans -> reconstruction -> cleanup -> normalised :class:`TreeMap`."""
    rec = reconstruct(scans, led_count)
    try:
        P, status, info = cleanup(rec.positions)
        P = normalise(P, status)
    except ValueError as e:
        raise ReconstructionError(str(e)) from None
    meta = {
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "angles": [s.angle for s in scans],
        "angle_offsets": np.round(rec.angle_offsets, 2).tolist(),
        "focal_px": round(rec.focal, 1),
        "median_residual_px": rec.info["median_residual_px"],
        "outliers": info["outliers"],
        "views": rec.views.tolist(),
    }
    return TreeMap(P, status, meta), rec


def reconstruct(scans: list[AngleScan], led_count: int) -> Reconstruction:
    if len(scans) < 2:
        raise ReconstructionError("need scans from at least two view angles")
    obs = Observations.from_scans(scans, led_count)
    if len(obs.led) == 0:
        raise ReconstructionError("the scans have no ok detections")

    P_px, cx, cy, w = _weak_init(obs)
    f0 = DEFAULT_FOCAL * float(obs.sizes.max())
    P0 = P_px / f0  # weak scale = f / distance, and the distance is 1
    cam = _Cams(f=f0, cx=cx, cy=cy, dth=np.zeros(len(obs.angles)))
    P, cam, w = _refine(obs, P0, cam, w)

    e = np.linalg.norm(_project(obs, P, cam) - obs.uv, axis=1)
    inlier = _inliers(w, obs.conf) & np.isfinite(e)
    measured = _well_seen(obs, cam, inlier)
    n = led_count
    views = np.bincount(obs.led[inlier], minlength=n)
    sq = np.bincount(obs.led[inlier], weights=e[inlier] ** 2, minlength=n)
    residual = np.sqrt(sq / np.maximum(views, 1))
    P[~measured] = np.nan
    return Reconstruction(
        positions=P,
        measured=measured,
        views=views,
        residual=np.where(views > 0, residual, np.nan),
        focal=cam.f,
        angle_offsets=np.degrees(cam.dth),
        centers=np.stack([cam.cx, cam.cy], axis=1),
        info={"observations": int(len(obs.led)), "inliers": int(inlier.sum()),
              "median_residual_px": float(np.median(e[inlier])) if inlier.any() else None},
    )


# -- weak perspective start ---------------------------------------------------------------


def _weak_init(obs: Observations, iters: int = 40):
    """Points in px (scale 1), per-view axis position, and robust weights per detection."""
    n, nv = obs.led_count, len(obs.angles)
    th = np.radians(obs.angles)
    a = np.stack([np.cos(th), np.sin(th)], axis=1)[obs.view]  # lateral direction per obs
    u, v = obs.uv[:, 0], obs.uv[:, 1]
    cx = obs.sizes[:, 0] / 2
    cy = obs.sizes[:, 1] / 2
    w = obs.conf.copy()
    XZ = np.zeros((n, 2))
    Y = np.zeros(n)
    scale = 0.05 * float(obs.sizes[:, 1].max())  # robust scale, px; tightened as it settles

    for _ in range(iters):
        # heights: Y = cy - v
        Y = _wmean(obs.led, w, cy[obs.view] - v, n)
        cy = _wmean(obs.view, w, v + Y[obs.led], nv)
        shift = cy[0] - obs.sizes[0, 1] / 2  # gauge: view 0's axis at the image centre
        cy -= shift
        Y -= shift
        # lateral: u - cx = a · (X, Z)
        A = np.zeros((n, 2, 2))
        np.add.at(A, obs.led, w[:, None, None] * a[:, :, None] * a[:, None, :])
        rhs = np.zeros((n, 2))
        np.add.at(rhs, obs.led, w[:, None] * a * (u - cx[obs.view])[:, None])
        XZ = np.linalg.solve(A + 1e-9 * np.eye(2), rhs[..., None])[..., 0]
        cx = _wmean(obs.view, w, u - (a * XZ[obs.led]).sum(1), nv)
        ok = _spread(A) > MIN_SPREAD
        if ok.any():  # gauge: LEDs centred on the axis
            m = XZ[ok].mean(axis=0)
            XZ -= m
            cx += np.stack([np.cos(th), np.sin(th)], axis=1) @ m
        # robust re-weighting
        eu = u - cx[obs.view] - (a * XZ[obs.led]).sum(1)
        ev = cy[obs.view] - v - Y[obs.led]
        e = np.hypot(eu, ev)
        scale = max(min(scale, 3.0 * float(np.median(e))), 1.0)
        w = obs.conf / (1.0 + (e / scale) ** 2)

    P = np.stack([XZ[:, 0], Y, XZ[:, 1]], axis=1)
    return P, cx, cy, w


def _wmean(idx: np.ndarray, w: np.ndarray, x: np.ndarray, n: int) -> np.ndarray:
    num = np.bincount(idx, weights=w * x, minlength=n)
    den = np.bincount(idx, weights=w, minlength=n)
    return np.divide(num, den, out=np.zeros(n), where=den > 0)


def _spread(A: np.ndarray) -> np.ndarray:
    """min/max eigenvalue of each 2x2 lateral normal matrix (0 = depth undetermined)."""
    eig = np.linalg.eigvalsh(A)
    return np.divide(eig[:, 0], eig[:, 1], out=np.zeros(len(A)), where=eig[:, 1] > 0)


# -- perspective refinement ---------------------------------------------------------------


@dataclass
class _Cams:
    f: float
    cx: np.ndarray
    cy: np.ndarray
    dth: np.ndarray  # radians

    def vector(self) -> np.ndarray:
        return np.concatenate([[self.f], self.cx, self.cy, self.dth])

    @classmethod
    def from_vector(cls, x: np.ndarray, nv: int) -> _Cams:
        return cls(f=float(x[0]), cx=x[1 : 1 + nv], cy=x[1 + nv : 1 + 2 * nv],
                   dth=x[1 + 2 * nv : 1 + 3 * nv])


def _geometry(obs: Observations, P: np.ndarray, cam: _Cams):
    phi = np.radians(obs.angles) + cam.dth
    r = np.stack([np.cos(phi), np.zeros_like(phi), np.sin(phi)], axis=1)[obs.view]
    b = np.stack([-np.sin(phi), np.zeros_like(phi), np.cos(phi)], axis=1)[obs.view]
    p = P[obs.led]
    x = (p * r).sum(1)
    pb = (p * b).sum(1)
    d = 1.0 - pb
    return p, r, b, x, pb, d


def _project(obs: Observations, P: np.ndarray, cam: _Cams) -> np.ndarray:
    p, _, _, x, _, d = _geometry(obs, P, cam)
    u = cam.cx[obs.view] + cam.f * x / d
    v = cam.cy[obs.view] - cam.f * p[:, 1] / d
    return np.stack([u, v], axis=1)


def _refine(obs: Observations, P: np.ndarray, cam: _Cams, w: np.ndarray,
            rounds: int = 5, iters: int = 12):
    """Joint Levenberg-Marquardt over points and cameras, re-weighting between rounds."""
    n, nv = obs.led_count, len(obs.angles)
    k = 1 + 3 * nv
    # priors on δθ: view 0 is fixed; the others stay near the nominal angle unless the
    # data says otherwise (σ ≈ 10°)
    prior = np.full(nv, 1 / np.radians(10.0) ** 2)
    prior[0] = 1e12

    for rnd in range(rounds):
        use = _well_seen(obs, cam, _inliers(w, obs.conf))
        sel = use[obs.led]
        if not sel.any():
            raise ReconstructionError("no LED was seen well enough from two directions")
        sub = Observations(obs.led[sel], obs.view[sel], obs.uv[sel], obs.conf[sel],
                           obs.angles, obs.sizes, n)
        sw = np.sqrt(w[sel])
        lam = 1e-3

        def cost(P_, cam_):
            r = (_project(sub, P_, cam_) - sub.uv) * sw[:, None]
            return float((r**2).sum() + (prior * cam_.dth**2).sum())

        current = cost(P, cam)
        for _ in range(iters):
            step = _lm_step(sub, P, cam, sw, prior, lam, use, k, nv)
            P_new, cam_new = P + step[0], _Cams.from_vector(cam.vector() + step[1], nv)
            sane = np.isfinite(P_new[use]).all() and cam_new.f > 0
            new = cost(P_new, cam_new) if sane else np.inf
            if new < current:
                done = (current - new) < 1e-7 * current
                P, cam, current = P_new, cam_new, new
                lam = max(lam / 3, 1e-9)
                if done:
                    break
            else:
                lam *= 10
                if lam > 1e8:
                    break

        # LEDs left out (e.g. a poor weak-perspective start) get another chance with
        # the improved cameras
        P[~use] = _triangulate(obs, cam, ~use)[~use]
        e = np.linalg.norm(_project(obs, P, cam) - obs.uv, axis=1)
        good = e[use[obs.led]]
        scale = max(2.5 * float(np.median(good)), MIN_SCALE_PX) if len(good) else 1.0
        w = obs.conf / (1.0 + (e / scale) ** 2)
    return P, cam, w


def _triangulate(obs: Observations, cam: _Cams, leds: np.ndarray, iters: int = 8) -> np.ndarray:
    """Robust linear triangulation of the selected LEDs with the cameras fixed.

    Each detection puts its LED on a ray: ``(r + α b)·P = α`` and ``(e_y + β b)·P = β``
    with ``α = (u − cx)/f`` and ``β = (cy − v)/f``. Solved by confidence-weighted least
    squares, re-weighted (Cauchy, shrinking scale) so a stray detection loses its pull.
    """
    n = obs.led_count
    sel = leds[obs.led]
    o = Observations(obs.led[sel], obs.view[sel], obs.uv[sel], obs.conf[sel],
                     obs.angles, obs.sizes, n)
    P = np.full((n, 3), np.nan)
    if not len(o.led):
        return P
    phi = np.radians(o.angles) + cam.dth
    r = np.stack([np.cos(phi), np.zeros_like(phi), np.sin(phi)], axis=1)[o.view]
    b = np.stack([-np.sin(phi), np.zeros_like(phi), np.cos(phi)], axis=1)[o.view]
    alpha = (o.uv[:, 0] - cam.cx[o.view]) / cam.f
    beta = (cam.cy[o.view] - o.uv[:, 1]) / cam.f
    rows = np.stack([r + alpha[:, None] * b, np.array([0.0, 1, 0]) + beta[:, None] * b], axis=1)
    rhs = np.stack([alpha, beta], axis=1)
    w = o.conf.copy()
    scale = 0.03 * float(o.sizes.max())
    for _ in range(iters):
        A = np.zeros((n, 3, 3))
        np.add.at(A, o.led, w[:, None, None] * np.einsum("mai,maj->mij", rows, rows))
        g = np.zeros((n, 3))
        np.add.at(g, o.led, w[:, None] * np.einsum("mai,ma->mi", rows, rhs))
        P = np.linalg.solve(A + 1e-9 * np.eye(3), g[..., None])[..., 0]
        e = np.linalg.norm(_project(o, P, cam) - o.uv, axis=1)
        w = o.conf / (1.0 + (e / scale) ** 2)
        scale = max(scale / 2, 2 * MIN_SCALE_PX)
    P[np.bincount(o.led, minlength=n) == 0] = np.nan
    return P


def _inliers(w: np.ndarray, conf: np.ndarray) -> np.ndarray:
    """Detections within 3 robust scales of the model (Cauchy weight > 1/10)."""
    return w > conf / (1.0 + INLIER_SCALES**2) * 1.0001


def _lm_step(obs, P, cam, sw, prior, lam, use, k, nv):
    """One damped Gauss-Newton step, eliminating the points (Schur complement)."""
    n = obs.led_count
    p, r, b, x, pb, d = _geometry(obs, P, cam)
    f = cam.f
    y = p[:, 1]
    m = len(obs.led)
    pred = _project(obs, P, cam)
    res = (pred - obs.uv) * sw[:, None]  # (M, 2)

    ey = np.array([0.0, 1.0, 0.0])
    Jp = np.empty((m, 2, 3))
    Jp[:, 0] = f * (r / d[:, None] + (x / d**2)[:, None] * b)
    Jp[:, 1] = -f * (ey / d[:, None] + (y / d**2)[:, None] * b)
    Jc = np.zeros((m, 2, k))
    Jc[:, 0, 0] = x / d
    Jc[:, 1, 0] = -y / d
    rows = np.arange(m)
    Jc[rows, 0, 1 + obs.view] = 1.0
    Jc[rows, 1, 1 + nv + obs.view] = 1.0
    Jc[rows, 0, 1 + 2 * nv + obs.view] = f * (pb / d - x**2 / d**2)
    Jc[rows, 1, 1 + 2 * nv + obs.view] = f * y * x / d**2
    Jp *= sw[:, None, None]
    Jc *= sw[:, None, None]

    Hpp = np.zeros((n, 3, 3))
    np.add.at(Hpp, obs.led, np.einsum("mai,maj->mij", Jp, Jp))
    Hpc = np.zeros((n, 3, k))
    np.add.at(Hpc, obs.led, np.einsum("mai,maj->mij", Jp, Jc))
    gp = np.zeros((n, 3))
    np.add.at(gp, obs.led, np.einsum("mai,ma->mi", Jp, res))
    Hcc = np.einsum("mai,maj->ij", Jc, Jc)
    gc = np.einsum("mai,ma->i", Jc, res)
    dth_slice = slice(1 + 2 * nv, 1 + 3 * nv)
    Hcc[dth_slice, dth_slice] += np.diag(prior)
    gc[dth_slice] += prior * cam.dth

    Hpp[~use] = np.eye(3)  # unused LEDs: no data, no step
    Hpp = Hpp + lam * Hpp * np.eye(3) + 1e-12 * np.eye(3)
    Hcc = Hcc + lam * np.diag(np.diag(Hcc)) + 1e-12 * np.eye(k)
    Hinv = np.linalg.inv(Hpp)
    HcpHinv = np.einsum("nic,nij->ncj", Hpc, Hinv)  # (n, k, 3)
    S = Hcc - np.einsum("ncj,njd->cd", HcpHinv, Hpc)
    rhs = -gc + np.einsum("ncj,nj->c", HcpHinv, gp)
    dc = np.linalg.solve(S, rhs)
    dp = -np.einsum("nij,nj->ni", Hinv, gp + Hpc @ dc)
    dp[~use] = 0.0
    return dp, dc


def _well_seen(obs: Observations, cam: _Cams, inlier: np.ndarray) -> np.ndarray:
    """LEDs with inlier views spread widely enough round the tree to fix their depth."""
    n = obs.led_count
    phi = np.radians(obs.angles) + cam.dth
    a = np.stack([np.cos(phi), np.sin(phi)], axis=1)[obs.view[inlier]]
    A = np.zeros((n, 2, 2))
    np.add.at(A, obs.led[inlier], a[:, :, None] * a[:, None, :])
    return _spread(A) > MIN_SPREAD
