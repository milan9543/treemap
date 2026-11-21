"""End to end without a browser: walk round the simulated tree once while the LEDs
flash their codes, then track, decode and solve, and compare with the true positions."""

from __future__ import annotations

import numpy as np

from tests.walk_render import walk_round
from treemap.scan.evaluate import evaluate
from treemap.scan.free import Round, build_map
from treemap.sim.tree import TreeSpec, generate_tree


def test_one_lap_maps_most_leds_to_within_a_centimetre(tmp_path):
    tree = generate_tree(TreeSpec.uniform(400), seed=3)
    n = tree.led_count
    walk_round(tree).save(tmp_path / "round_01.npz")
    tree_map, _ = build_map([Round.load(tmp_path / "round_01.npz")], n)

    counts = tree_map.counts()
    assert counts["ok"] >= 0.8 * n, counts
    ev = evaluate(tree_map, tree)
    ok = ev.summary("ok")
    assert ok["median"] * ev.height_m < 0.01, ok  # metres
    assert ok["p95"] * ev.height_m < 0.03, ok
    assert np.isfinite(tree_map.positions).all()


def test_more_leds_get_longer_codes_that_still_repair():
    from treemap.scan.code import code_lookup, codewords, repair

    assert codewords(728).shape == (728, 7)  # up to 728: 6 digits + check, as before
    codes = codewords(800)
    assert codes.shape == (800, 8)
    assert len(code_lookup(800)) == 800  # all distinct
    assert codewords(5000).shape == (5000, 9)
    for i in (0, 399, 799):
        damaged = [int(d) for d in codes[i]]
        damaged[3] = None  # a symbol the camera missed
        assert code_lookup(800)[tuple(repair(damaged))] == i
