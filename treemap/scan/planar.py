"""2D LED positions for a flat layout: strips laid on the floor or taped to a wall.

All the LEDs lie in one plane, so any two photos of them are related by a homography
(a plane-to-plane perspective mapping) and no 3D solve is needed:

1. **Reference**: the frame that sees the most LEDs; the map starts as its pixels.
2. **Register**: each other frame that shares enough LEDs with the map is mapped onto it
   by a homography (RANSAC). This runs in passes, so a frame that only overlaps frames
   registered in an earlier pass joins too. Each LED's map position is the median of
   its mapped observations.
3. **Refine**: each frame's homography is fitted again to the finished map, and the map
   rebuilt.
4. **Flatten**: the reference photo looks at the plane at an angle, which squashes its
   far side. The plane's tilt (two angles; the focal length comes from the camera's
   field of view) is chosen to make the spacing between neighbouring LEDs as even as it
   is on the strip, and the map is re-projected as seen square-on.

The camera may stay still (on a stand) or move round; it only has to see the LEDs.
Positions come out with x to the right and y up as in the reference photo, z = 0.
"""

from __future__ import annotations

import cv2
import numpy as np
from scipy.optimize import least_squares

from treemap.scan.sfm import SfmError, SfmResult

MIN_SHARED = 10  # LEDs a frame must share with the map to be registered
RANSAC_PX = 3.0  # px, homography inlier threshold
MIN_VIEWS = 3  # frames an LED must be seen in (consistently) to count as measured
MAX_FRAMES = 400  # frames used, spread evenly; a still camera repeats itself anyway
MAX_TILT = 2.5  # bound on the tilt parameters (tan of the angle: about 68°)


def _views(frame: np.ndarray, led: np.ndarray, uv: np.ndarray) -> dict[int, tuple]:
    """Per frame with enough LEDs: (LED ids, their pixels), one per LED."""
    order = np.lexsort((led, frame))
    frame, led, uv = frame[order], led[order], uv[order]
    ids, start = np.unique(frame, return_index=True)
    stops = np.append(start[1:], len(frame))
    views = {}
    for fid, a, b in zip(ids, start, stops):
        leds, first = np.unique(led[a:b], return_index=True)
        if len(leds) >= MIN_SHARED:
            views[int(fid)] = (leds, uv[a:b][first].astype(float))
    if len(views) > MAX_FRAMES:
        keep = sorted(views)
        keep = [keep[i] for i in np.round(np.linspace(0, len(keep) - 1, MAX_FRAMES)).astype(int)]
        views = {k: views[k] for k in keep}
    return views


def _apply(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(pts.reshape(-1, 1, 2), H).reshape(-1, 2)


def _register(leds: np.ndarray, pts: np.ndarray, known: dict[int, np.ndarray]) -> np.ndarray | None:
    have = np.array([int(i) in known for i in leds])
    if have.sum() < MIN_SHARED:
        return None
    dst = np.array([known[int(i)] for i in leds[have]])
    H, mask = cv2.findHomography(pts[have], dst, cv2.RANSAC, RANSAC_PX)
    if H is None or mask is None or mask.sum() < MIN_SHARED:
        return None
    return H


def _build(views: dict, H: dict) -> tuple[dict[int, np.ndarray], dict[int, int], np.ndarray]:
    """Each LED's median mapped position, its inlier count, and every observation's
    distance from its LED's median (px)."""
    leds = np.concatenate([views[f][0] for f in H])
    pts = np.concatenate([_apply(H[f], views[f][1]) for f in H])
    order = np.argsort(leds, kind="stable")
    leds, pts = leds[order], pts[order]
    ids, start = np.unique(leds, return_index=True)
    stops = np.append(start[1:], len(leds))
    known, count, resid = {}, {}, []
    for i, a, b in zip(ids, start, stops):
        med = np.median(pts[a:b], axis=0)
        d = np.linalg.norm(pts[a:b] - med, axis=1)
        known[int(i)] = med
        count[int(i)] = int((d < RANSAC_PX).sum())
        resid.append(d)
    return known, count, np.concatenate(resid) if resid else np.zeros(0)


# -- flattening ----------------------------------------------------------------------


def plane_coords(xy: np.ndarray, tilt: np.ndarray, f: float, c: np.ndarray) -> np.ndarray:
    """Pixels of a photo -> 2D coordinates on a plane tilted by ``tilt`` (the plane's
    normal is ``(tilt[0], tilt[1], 1)`` in camera axes). x follows the photo's right,
    y its up; the scale is arbitrary."""
    n = np.array([tilt[0], tilt[1], 1.0])
    n /= np.linalg.norm(n)
    rays = np.column_stack([(xy - c) / f, np.ones(len(xy))])
    X = rays / (rays @ n)[:, None]  # where each ray meets the plane n·X = 1
    e1 = np.array([1.0, 0, 0]) - n[0] * n
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)  # in the plane, pointing down the photo (camera +y) roughly
    if e2[1] < 0:
        e2 = -e2
    return np.column_stack([X @ e1, -(X @ e2)])


def flatten(xy: np.ndarray, led: np.ndarray, f: float, c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``(plane coordinates, tilt)`` for map pixels ``xy`` of LEDs ``led`` (sorted): the
    tilt that makes neighbouring LEDs most evenly spaced."""
    pair = np.flatnonzero(np.diff(led) == 1)  # consecutive LEDs, both in the map
    if len(pair) < 10:
        return plane_coords(xy, np.zeros(2), f, c), np.zeros(2)

    rays = np.column_stack([(xy - c) / f, np.ones(len(xy))])

    def residuals(p: np.ndarray) -> np.ndarray:
        n = np.array([p[0], p[1], 1.0])
        if (rays @ n).min() < 0.05 * np.linalg.norm(n):  # horizon among the LEDs
            return np.full(len(pair) + 2, 10.0)
        q = plane_coords(xy, p[:2], f, c)
        d = np.linalg.norm(q[pair + 1] - q[pair], axis=1)
        return np.concatenate([np.log(np.maximum(d, 1e-9)) - p[2], 0.02 * p[:2]])

    start = np.log(np.median(np.linalg.norm(xy[pair + 1] - xy[pair], axis=1)) / f)
    best = None
    for t0 in ([0, 0], [0, 0.6], [0, -0.6], [0.6, 0], [-0.6, 0]):  # avoid a wrong valley
        if residuals(np.array([*t0, start]))[0] == 10.0:
            continue
        r = least_squares(residuals, [*t0, start], loss="soft_l1", f_scale=0.1,
                          bounds=([-MAX_TILT, -MAX_TILT, -np.inf], [MAX_TILT, MAX_TILT, np.inf]))
        if best is None or r.cost < best.cost:
            best = r
    tilt = best.x[:2] if best is not None else np.zeros(2)
    return plane_coords(xy, tilt, f, c), tilt


# -- the solve -----------------------------------------------------------------------


def solve(frame: np.ndarray, led: np.ndarray, uv: np.ndarray, size: tuple[int, int],
          f0: float, led_count: int) -> SfmResult:
    """2D positions (z = 0) from ``(frame id, LED, pixel)`` observations of a flat layout."""
    if len(frame) == 0:
        raise SfmError("no LEDs were identified")
    views = _views(np.asarray(frame), np.asarray(led), np.asarray(uv, dtype=float))
    if not views:
        raise SfmError(f"no photo saw {MIN_SHARED} or more LEDs; point the camera at the LEDs")
    ref = max(views, key=lambda k: len(views[k][0]))
    H = {ref: np.eye(3)}
    known = {int(i): p for i, p in zip(*views[ref])}
    for _ in range(6):  # passes: frames that overlap the growing map join
        added = 0
        for fid in sorted(views, key=lambda k: -len(views[k][0])):
            if fid not in H and (h := _register(*views[fid], known)) is not None:
                H[fid] = h
                added += 1
        known, count, resid = _build(views, H)
        if not added:
            break
    for _ in range(2):  # refine against the finished map
        for fid in H:
            if fid != ref and (h := _register(*views[fid], known)) is not None:
                H[fid] = h
        known, count, resid = _build(views, H)

    ids = np.array(sorted(i for i in known if count[i] >= MIN_VIEWS), dtype=int)
    ids = ids[ids < led_count]
    if len(ids) < 2:
        raise SfmError("too few LEDs were seen consistently; keep the LEDs in view")
    c = np.array([size[0] / 2 - 0.5, size[1] / 2 - 0.5])
    xy = np.array([known[int(i)] for i in ids])
    plane, tilt = flatten(xy, ids, f0, c)

    positions = np.full((led_count, 3), np.nan)
    positions[ids, :2] = plane
    positions[ids, 2] = 0.0
    measured = np.zeros(led_count, dtype=bool)
    measured[ids] = True
    views_n = np.zeros(led_count, dtype=int)
    for i, k in count.items():
        if i < led_count:
            views_n[i] = k
    n = np.array([tilt[0], tilt[1], 1.0])
    info = {
        "shape": "flat",
        "keyframes": len(views),
        "registered": len(H),
        "median_residual_px": round(float(np.median(resid)), 3) if len(resid) else None,
        "focal_px": round(float(f0), 1),
        "tilt_deg": round(float(np.degrees(np.arccos(1 / np.linalg.norm(n)))), 1),
    }
    return SfmResult(positions, measured, views_n, np.zeros(led_count), float(f0),
                     np.array(sorted(H)), np.zeros((0, 3)), info)
