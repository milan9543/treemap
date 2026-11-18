"""Clean up reconstructed positions using the strip's wiring order, then normalise.

Neighbouring LEDs on a strip are at most one LED spacing apart (~7 cm), so the chord
between LEDs ``a`` and ``b`` can't be much longer than ``|b − a|`` spacings. The spacing
(``pitch``) is estimated from the data as the median distance between consecutive LEDs.

* **Outliers**: a measured LED that is too far from its nearest measured neighbour on
  *both* sides is dropped (typically a reflection detected in two views). Being far
  from only one side is a strip boundary or a gap, not an error.
* **Filling**: dropped and unmeasured LEDs are interpolated along the strip index
  between the nearest good LEDs, if the gap is short and its ends are consistent.

Statuses: ``ok`` (measured), ``interpolated`` (filled from good neighbours) and
``failed`` (long gap, strip end or a break; the position is only a rough guess).
"""

from __future__ import annotations

import numpy as np

STATUSES = ("ok", "interpolated", "failed")
MAX_GAP = 4  # missing LEDs in a row that can still be interpolated reliably


def chord_limit(gap: np.ndarray | int, pitch: float) -> np.ndarray:
    """Largest plausible distance between LEDs ``gap`` indices apart (plus noise)."""
    return pitch * (1.25 * np.asarray(gap) + 0.75)


def estimate_pitch(P: np.ndarray, good: np.ndarray) -> float:
    pair = good[:-1] & good[1:]
    if not pair.any():
        raise ValueError("no two consecutive LEDs were measured; can't estimate LED spacing")
    return float(np.median(np.linalg.norm(P[1:][pair] - P[:-1][pair], axis=1)))


def find_outliers(P: np.ndarray, good: np.ndarray, pitch: float) -> np.ndarray:
    """Good LEDs inconsistent with the nearest good LED on both sides (within reach)."""
    idx = np.flatnonzero(good)
    out = np.zeros(len(P), dtype=bool)
    if len(idx) < 3:
        return out

    def side_ok(j: np.ndarray, k: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        gap = np.abs(k - j)
        near = gap <= MAX_GAP + 1  # a neighbour close enough in index to judge by
        ok = np.linalg.norm(P[j] - P[k], axis=1) <= chord_limit(gap, pitch)
        return near, ok

    left_near, left_ok = side_ok(idx[1:], idx[:-1])
    left_near = np.concatenate([[False], left_near])
    left_ok = np.concatenate([[False], left_ok])
    right_near, right_ok = side_ok(idx[:-1], idx[1:])
    right_near = np.concatenate([right_near, [False]])
    right_ok = np.concatenate([right_ok, [False]])

    judged = left_near | right_near
    consistent = (left_near & left_ok) | (right_near & right_ok)
    out[idx[judged & ~consistent]] = True
    return out


def cleanup(positions: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """``(positions, status, info)``; ``positions`` has NaN rows for unmeasured LEDs."""
    P = np.array(positions, dtype=float)
    n = len(P)
    good = np.isfinite(P).all(axis=1)
    if good.sum() < 2:
        raise ValueError("fewer than two LEDs were measured")
    pitch = estimate_pitch(P, good)

    outliers = np.zeros(n, dtype=bool)
    for _ in range(10):
        bad = find_outliers(P, good, pitch)
        if not bad.any():
            break
        outliers |= bad
        good &= ~bad

    status = np.where(good, "ok", "failed").astype("<U12")
    idx = np.flatnonzero(good)
    out = P.copy()
    for i in np.flatnonzero(~good):
        k = np.searchsorted(idx, i)
        j = idx[k - 1] if k > 0 else None  # nearest good below
        m = idx[k] if k < len(idx) else None  # nearest good above
        joined = (
            j is not None and m is not None
            and np.linalg.norm(P[m] - P[j]) <= chord_limit(m - j, pitch)
        )
        if joined:
            t = (i - j) / (m - j)
            out[i] = (1 - t) * P[j] + t * P[m]
            if m - j - 1 <= MAX_GAP:
                status[i] = "interpolated"
        else:  # strip end or a break between strips: copy the nearer good LED (a guess
            # unless it is the very next one)
            if j is not None and m is not None:
                j, m = (j, None) if i - j <= m - i else (None, m)
            near = j if j is not None else m
            out[i] = P[near]
            if abs(i - near) == 1:
                status[i] = "interpolated"
    info = {"pitch": pitch, "outliers": np.flatnonzero(outliers).tolist()}
    return out, status, info


def normalise(P: np.ndarray, status: np.ndarray) -> np.ndarray:
    """y 0..1 over the ok LEDs; x and z centred on the trunk, at the same scale.

    The trunk is taken as the mean x/z of the ok LEDs, which the spiral winds round.
    """
    ok = status == "ok"
    y0, y1 = P[ok, 1].min(), P[ok, 1].max()
    if y1 <= y0:
        raise ValueError("the measured LEDs have no height range")
    centre = np.array([P[ok, 0].mean(), y0, P[ok, 2].mean()])
    return (P - centre) / (y1 - y0)
