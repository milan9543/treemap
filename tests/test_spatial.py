"""Map geometry, the map source, and the 3D effects."""

import numpy as np
import pytest

from treemap.effects import EffectContext, ParamError, create_effect
from treemap.mapping.model import TreeMap
from treemap.mapping.source import MapSource
from treemap.sim.tree import TreeSpec, generate_tree


def tree_map(positions):
    P = np.asarray(positions, dtype=float)
    return TreeMap(P, np.array(["ok"] * len(P), dtype="<U12"))


def ctx_for(m):
    return EffectContext(n=m.led_count, rng=np.random.default_rng(0), tree_map=lambda: m)


def test_geometry_cylindrical_and_front_view():
    m = tree_map([[0, 0, 0.5], [0.5, 0.5, 0], [-0.25, 1, 0], [np.nan] * 3])
    g = m.geometry
    assert g.valid.tolist() == [True, True, True, False]
    assert np.allclose(g.theta[:3], [0, np.pi / 2, -np.pi / 2])  # 0 at front (+z), towards +x
    assert np.allclose(g.r[:3], [0.5, 0.5, 0.25])
    assert np.allclose(g.u[:3], [0.5, 1.0, 0.25]) and np.allclose(g.v[:3], [0, 0.5, 1])
    assert not g.xyz[3].any()  # no NaN for effects to trip over


def test_plane_lights_a_level_band_and_blacks_out_unknown_leds():
    ys = np.linspace(0, 1, 101)
    P = np.stack([0.2 * np.cos(ys * 40), ys, 0.2 * np.sin(ys * 40)], axis=1)
    P[50] = np.nan
    m = tree_map(P)
    plane = create_effect("plane", ctx_for(m), {"speed": 0.5, "width": 0.05})
    frame = plane.render(1.0)  # half way: the plane's at the middle of the tree
    lit = np.flatnonzero(frame.max(axis=1) > 0)
    assert 50 not in lit and len(lit) > 4
    assert np.all(np.abs(ys[lit] - 0.5) < 0.05)

    plane.set_params({"direction": "around"})
    lit = plane.render(0.0).max(axis=1) > 0  # beam pointing to the front (+z)
    assert lit.any() and (P[lit, 2] > 0).all()


def test_candy_spiral_paints_every_led_in_one_of_two_colours():
    ys = np.linspace(0, 1, 200)
    m = tree_map(np.stack([0.3 * np.cos(ys * 50), ys, 0.3 * np.sin(ys * 50)], axis=1))
    frame = create_effect("spiral", ctx_for(m), {"style": "candy"}).render(0.3)
    red = (frame == (255, 0, 0)).all(axis=1)
    white = (frame == (255, 255, 255)).all(axis=1)
    assert (red | white).all() and 0.3 < red.mean() < 0.5  # width 0.4 of each period


def test_map_source_switches_to_the_normalised_truth(tmp_path):
    tree = generate_tree(TreeSpec.uniform(50, 1), seed=3)
    tree.save(tmp_path / "tree.json")
    source = MapSource(tmp_path / "map.json", tmp_path / "tree.json")
    assert source.choices == ["scanned", "truth"] and source() is None
    assert "scan the tree first" in source.missing()
    source.select("truth")
    m = source()
    assert m.led_count == 50 and (m.status == "ok").all()
    assert m.positions[:, 1].min() == 0 and m.positions[:, 1].max() == pytest.approx(1)
    with pytest.raises(ValueError):
        MapSource(tmp_path / "map.json").select("truth")  # no truth outside the simulator


def test_3d_effect_without_a_map_says_what_to_do(tmp_path):
    ctx = EffectContext(n=10, tree_map=MapSource(tmp_path / "map.json", tmp_path / "t.json"))
    with pytest.raises(ParamError, match="true tree"):
        create_effect("rainbow3d", ctx)


def test_fill_rises_from_the_bottom_in_a_new_colour():
    ys = np.linspace(0, 1, 100)
    m = tree_map(np.stack([0.2 * np.cos(ys * 40), ys, 0.2 * np.sin(ys * 40)], axis=1))
    fill = create_effect("fill", ctx_for(m), {"seconds": 4, "wave": 0})
    frame = fill.render(2.0)  # half way through the first fill: red rising over white
    assert (frame[:30] == (255, 0, 0)).all() and (frame[-30:] == (255, 255, 255)).all()
