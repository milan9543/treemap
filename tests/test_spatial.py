"""Map geometry, the map source, and the 3D effects."""

import numpy as np
import pytest

from treemap.effects import EffectContext, ParamError, create_effect, describe_effects
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
    fill = create_effect("fill", ctx_for(m), {"speed": 0.25, "hold": 0, "wave": 0})
    frame = fill.render(2.0)  # half way through the first fill: red rising over white
    assert (frame[:30] == (255, 0, 0)).all() and (frame[-30:] == (255, 255, 255)).all()


def test_3d_effects_only_use_christmas_colours():
    t = generate_tree(TreeSpec.uniform(120), seed=4)
    m = tree_map(t.normalised_positions())
    for fx in describe_effects(m.led_count):
        if fx["group"] != "3D":
            continue
        variants = [{}] + [{p["name"]: True} for p in fx["params"] if p["kind"] == "bool"] + [
            {p["name"]: c} for p in fx["params"] if p["kind"] == "choice" for c in p["choices"]]
        for params in variants:
            e = create_effect(fx["name"], ctx_for(m), params)
            for t_ in (0.3, 1.7, 4.1, 9.0):
                rgb = e.render(t_)
                # no blue, purple or cyan: blue never outshines both red and green
                assert (rgb[:, 2] <= rgb[:, :2].max(axis=1) + 1).all(), (fx["name"], params)


def test_background_colours_the_leds_the_animation_leaves_alone():
    t = generate_tree(TreeSpec.uniform(200), seed=4)
    m = tree_map(t.normalised_positions())
    bg = np.array([255, 0, 0]) * 0.5
    with_bg = [fx["name"] for fx in describe_effects(m.led_count)
               if fx["group"] == "3D" and any(p["name"] == "background" for p in fx["params"])]
    assert {"plane", "spiral", "sphere", "ripple", "radar", "fireflies"} <= set(with_bg)
    for name in with_bg:
        e = create_effect(name, ctx_for(m), {"background": "red", "background_level": 0.5})
        frame = e.render(1.7)
        at_bg = (np.abs(frame - bg).max(axis=1) < 4).mean()
        assert at_bg > 0.25, name  # most LEDs are untouched and show the background
        off = create_effect(name, ctx_for(m), {}).render(1.7)
        assert (np.abs(off).max(axis=1) < 4).mean() > 0.25, name  # default: off


def test_fill_outwards_grows_from_the_middle_in_a_new_colour():
    t = generate_tree(TreeSpec.uniform(200), seed=4)
    m = tree_map(t.normalised_positions())
    fill = create_effect("fillout", ctx_for(m), {"speed": 0.25, "hold": 0, "wave": 0})
    frame = fill.render(2.0)  # half way through the first fill: red growing into white
    g = m.geometry
    dist = np.linalg.norm(g.xyz - [0, (g.lo[1] + g.hi[1]) / 2, 0], axis=1)
    near, far = dist < np.percentile(dist, 20), dist > np.percentile(dist, 80)
    assert (frame[near] == (255, 0, 0)).all() and (frame[far] == (255, 255, 255)).all()


def test_fill_holds_still_then_fills_in_the_next_palette_colour():
    m = tree_map(np.stack([np.zeros(50), np.linspace(0, 1, 50), np.zeros(50)], axis=1))
    fill = create_effect("fillout", ctx_for(m), {"speed": 0.5, "hold": 3, "wave": 0,
                                                 "palette": "green & gold"})
    for t in (2.2, 4.9):  # filled after 2 s, then still for 3 s: all green
        assert (fill.render(t) == (0, 190, 20)).all()
    assert (fill.render(6.0) == (255, 140, 0)).any()  # the next fill brings gold


def test_burst_explosion_flashes_then_throws_sparks_that_fade():
    t = generate_tree(TreeSpec.uniform(400), seed=4)
    m = tree_map(t.normalised_positions())
    e = create_effect("sphere", ctx_for(m), {"rate": 0.1, "size": 0.4, "fade": 1.5})
    e.render(0.0)
    b = e.bursts[0]
    dist = np.linalg.norm(m.geometry.xyz - b.centre, axis=1)
    flash = e.render(0.05)
    assert (flash[dist < 0.03] > 200).all()  # white-hot at the centre
    frame = e.render(0.6)  # sparks out near their reach, cooled to the burst's colour
    lit = frame.max(axis=1) > 60
    assert lit[dist > 0.15].sum() >= 5 and not lit[dist > 0.6].any()
    colour = b.rgb / max(b.rgb.max(), 1)
    shade = frame[lit] / frame[lit].max(axis=1, keepdims=True)
    assert np.allclose(shade, colour, atol=0.05)
    if len(e.bursts) == 1:  # (unless another burst came along)
        assert e.render(1.55).max() < 1  # burnt out


def test_fire_is_hot_at_the_bottom_and_dark_at_the_top():
    t = generate_tree(TreeSpec.uniform(300), seed=4)
    m = tree_map(t.normalised_positions())
    e = create_effect("fire", ctx_for(m), {"sparks": 0})
    h = m.geometry.h
    for t_ in (0.5, 2.0, 7.3):
        light = e.render(t_).sum(axis=1)
        assert light[h < 0.15].mean() > 4 * light[h > 0.8].mean() + 1
