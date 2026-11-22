"""Which way a map faces: the front of a tree, the bottom of a flat layout (format 2)."""

import json

import numpy as np
import pytest

from tests.test_api import call, serve  # noqa: F401 - the fixture
from treemap.effects import EffectContext, create_effect
from treemap.mapping.model import TreeMap
from treemap.scan.free import follow


def spiral_tree(n=200):
    ys = np.linspace(0, 1, n)
    P = np.stack([0.3 * (1 - ys) * np.sin(ys * 50), ys, 0.3 * (1 - ys) * np.cos(ys * 50)], axis=1)
    return TreeMap(P, np.full(n, "ok", dtype="<U12"), {"shape": "tree"})


def test_a_plane_around_starts_at_the_front_you_set():
    m = spiral_tree().turned({"front_deg": 90})  # the LEDs at +x face the room
    plane = create_effect("plane", EffectContext(n=m.led_count, tree_map=lambda: m),
                          {"direction": "around"})
    lit = plane.render(0.0).max(axis=1) > 0
    x, z = m.positions[lit, 0], m.positions[lit, 2]
    out = np.hypot(x, z) > 0.1  # near the trunk, the beam's thickness (0.08) reaches round
    assert out.sum() > 10 and (x[out] > 0).all()  # +x as solved
    assert np.allclose(m.positions, spiral_tree().positions)  # positions stay as solved


def test_v1_maps_load_facing_as_solved_and_v2_keeps_the_orientation(tmp_path):
    d = spiral_tree().to_dict()
    assert d["version"] == 2 and "orientation" not in d
    d["version"] = 1
    m = TreeMap.from_dict(d)
    assert m.orientation is None and np.allclose(m.geometry.xyz, m.positions)

    m.turned({"front_deg": -30}).save(tmp_path / "map.json")
    assert TreeMap.load(tmp_path / "map.json").orientation == {"front_deg": 330.0}
    with pytest.raises(ValueError):
        m.turned({"rotate_deg": 90})  # that's for a flat layout


def test_a_flat_layout_turns_and_mirrors_and_stays_normalised():
    P = np.array([[0, 0, 0], [2, 0, 0], [2, 1, 0], [np.nan] * 3])  # wide: 2 across, 1 up
    m = TreeMap(P, np.array(["ok", "ok", "ok", "failed"], dtype="<U12"), {"shape": "flat"})
    g = m.turned({"rotate_deg": 90, "mirror": True}).geometry
    # mirrored, then a quarter turn anticlockwise: the layout stands 2 high
    assert np.isclose(g.xyz[:3, 1].min(), 0) and np.isclose(g.xyz[:3, 1].max(), 1)
    assert np.allclose(g.xyz[:3, 1], [1, 0, 0]) and np.isclose(g.xyz[:3, 0].mean(), 0)
    assert np.allclose(g.xyz[1:3, 0] - g.xyz[1, 0], [0, -0.5])  # LED 2 to the left of 1
    assert not g.valid[3]


def test_solving_again_keeps_the_front_though_the_heading_changes():
    before = spiral_tree().turned({"front_deg": 40})
    a = np.radians(75)  # the new solve's heading is somewhere else
    x, z = before.positions[:, 0], before.positions[:, 2]
    P = np.stack([x * np.cos(a) - z * np.sin(a), before.positions[:, 1],
                  x * np.sin(a) + z * np.cos(a)], axis=1)
    after = follow(TreeMap(P, before.status, {"shape": "tree"}), before)
    assert after.orientation == {"front_deg": 40.0}
    assert np.allclose(after.geometry.theta, before.geometry.theta, atol=1e-4)


def test_setting_the_front_from_the_page(serve):  # noqa: F811
    api, base = serve()
    assert call(base + "/map")[0] == 404
    spiral_tree(400).save(api.cfg.map_path)
    out = api.output

    status, _, m = call(base + "/map")
    assert status == 200 and m["orientation"] == {"front_deg": 0.0} and m["led_status"] == "o" * 400

    assert call(base + "/leds", {"mode": "stripe", "front_deg": 90})[0] == 200
    lit = out.frame.max(axis=1) > 0
    P = api._load_map().positions
    assert lit.any() and (np.degrees(np.arctan2(P[lit, 0], P[lit, 2])) > 70).all()
    assert call(base + "/leds", {"mode": "edge"})[0] == 400  # a tree has no edge

    status, _, m = call(base + "/map/orientation", {"front_deg": 90})
    assert status == 200 and m["orientation"] == {"front_deg": 90.0}
    assert json.loads(api.cfg.map_path.read_text())["orientation"] == {"front_deg": 90.0}
    call(base + "/leds", {"mode": "stripe"})  # now the saved front
    assert ((out.frame.max(axis=1) > 0) == lit).all()
    assert call(base + "/map/orientation", {"rotate_deg": 90})[0] == 400


def test_a_flat_maps_edge_on_the_leds(serve):  # noqa: F811
    api, base = serve()
    xs, ys = np.meshgrid(np.linspace(0, 1.6, 20), np.linspace(0, 1, 20))
    P = np.stack([xs.ravel(), ys.ravel(), np.zeros(400)], axis=1)
    TreeMap(P, np.full(400, "ok", dtype="<U12"), {"shape": "flat"}).save(api.cfg.map_path)
    out = api.output

    assert call(base + "/leds", {"mode": "edge", "rotate_deg": 180})[0] == 200
    white = (out.frame == 200).all(axis=1)
    red = (out.frame == (255, 0, 0)).all(axis=1)
    assert white.any() and (P[white, 1] > 0.85).all()  # turned over: the top rows are the bottom
    assert red.any() and (P[red, 0] > 1.35).all()  # and the right side the left
