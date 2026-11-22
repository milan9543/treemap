"""The 2D scan of a flat layout, end to end without a browser: a phone at the edge of
the layout films it at an angle while the LEDs flash their codes."""

from __future__ import annotations

import numpy as np
import pytest

from tests.walk_render import flat_layout, flat_round
from treemap.scan.free import add_round, build_map


def align_2d(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """``a`` moved onto ``b`` by the best rotation, scale and offset (no mirroring)."""
    ma, mb = a.mean(axis=0), b.mean(axis=0)
    A, B = a - ma, b - mb
    u, s, vt = np.linalg.svd(B.T @ A)
    d = np.sign(np.linalg.det(u @ vt))
    R = u @ np.diag([1, d]) @ vt
    scale = (s * [1, d]).sum() / (A ** 2).sum()
    return scale * A @ R.T + mb


@pytest.mark.parametrize("moving", [False, True])
def test_flat_scan_places_leds_to_within_a_centimetre(moving):
    truth = flat_layout(400, seed=1)
    tree_map, res = build_map([flat_round(truth, moving=moving)], 400, shape="flat")

    ok = tree_map.status == "ok"
    assert ok.mean() >= 0.85, tree_map.counts()
    assert np.allclose(tree_map.positions[:, 2], 0)
    # the photo's up is the map's up: the far side of the layout (-z) is at the top
    true_2d = np.column_stack([truth[:, 0], -truth[:, 2]])
    aligned = align_2d(tree_map.positions[ok, :2], true_2d[ok])
    err = np.linalg.norm(aligned - true_2d[ok], axis=1)
    assert np.median(err) < 0.01 and np.percentile(err, 95) < 0.03, (
        np.median(err), np.percentile(err, 95), res.info)
    # no mirroring: the alignment needed little rotation
    m = tree_map.positions[ok, :2] - tree_map.positions[ok, :2].mean(axis=0)
    t = true_2d[ok] - true_2d[ok].mean(axis=0)
    assert np.corrcoef(m[:, 0], t[:, 0])[0, 1] > 0.95


def test_a_round_of_something_else_is_left_out_and_flagged_as_not_flat():
    """A round that disagrees with the others (here: another layout; on a real scan the
    LEDs moved, or a 3D tree scanned as flat) mustn't spoil the map they made."""
    good = flat_round(flat_layout(400, seed=1))
    first, res = build_map([good], 400, shape="flat")
    assert res.info["agree"] > 0.9

    added = add_round([good], flat_round(flat_layout(400, seed=2)), 400, shape="flat", like=first)
    assert not added.kept
    assert added.tree_map is first
    assert "left out" in added.message and "look flat" in added.message
