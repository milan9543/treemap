import numpy as np
import pytest

from treemap.config import config_from_dict
from treemap.sim.tree import (
    HEIGHT_RANGE,
    PITCH_RANGE,
    RADIUS_RANGE,
    SimTree,
    SpecError,
    StripSpec,
    TreeSpec,
    generate_tree,
    spec_from_config,
    split_counts,
)

SEEDS = range(1, 41)


@pytest.fixture(scope="module")
def trees():
    return [generate_tree(seed=seed) for seed in SEEDS]


def strand_slices(tree):
    return [tree.positions[s.start : s.start + s.count] for s in tree.strands]


def spec(*strips, **kw):
    return TreeSpec(strips=[StripSpec(*s) if isinstance(s, tuple) else s for s in strips], **kw)


# -- default random trees ---------------------------------------------------------------


def test_same_seed_same_tree():
    a, b = generate_tree(seed=123), generate_tree(seed=123)
    assert np.array_equal(a.positions, b.positions)
    assert a.to_dict() == b.to_dict()


def test_different_seeds_differ():
    assert not np.allclose(generate_tree(seed=1).positions, generate_tree(seed=2).positions)


def test_no_seed_picks_and_records_one():
    tree = generate_tree()
    assert tree.seed > 0
    assert np.array_equal(generate_tree(seed=tree.seed).positions, tree.positions)


def test_seed_in_spec_is_used_and_argument_overrides_it():
    assert generate_tree(TreeSpec(seed=77)).seed == 77
    assert generate_tree(TreeSpec(seed=77), seed=5).seed == 5


def test_shape_and_dimensions(trees):
    for t in trees:
        assert t.positions.shape == (400, 3)
        assert np.isfinite(t.positions).all()
        assert HEIGHT_RANGE[0] <= t.height <= HEIGHT_RANGE[1]
        assert RADIUS_RANGE[0] <= t.radius <= RADIUS_RANGE[1]
        assert [s.count for s in t.strands] == [200, 200]
        assert [s.start for s in t.strands] == [0, 200]
        for s in t.strands:
            assert PITCH_RANGE[0] <= s.spacing <= PITCH_RANGE[1]
            assert s.coverage == 1.0
        assert t.warnings == []


def test_neighbours_on_a_strip_are_within_10cm(trees):
    for t in trees:
        for pts in strand_slices(t):
            gaps = np.linalg.norm(np.diff(pts, axis=0), axis=1)
            assert gaps.max() < 0.10, f"seed {t.seed}"
            # chords shrink where the wire doubles back at a branch, but never collapse
            assert gaps.min() > 0.01, f"seed {t.seed}: LEDs bunched together"


def test_leds_lie_on_the_tree(trees):
    for t in trees:
        y = t.positions[:, 1]
        r = np.hypot(t.positions[:, 0], t.positions[:, 2])
        assert y.min() >= 0 and y.max() <= t.height
        # inside the cone, allowing a little girth near the tip
        assert (r - t.cone_radius_at(y)).max() < 0.06, f"seed {t.seed}"
        assert r.min() > t.trunk_radius, f"seed {t.seed}: LED inside the trunk"


def test_leds_spread_over_height_and_angle(trees):
    for t in trees:
        y = t.positions[:, 1] / t.height
        assert y.min() < 0.15 and y.max() > 0.8
        theta = np.arctan2(t.positions[:, 2], t.positions[:, 0])
        hist, _ = np.histogram(theta, bins=8, range=(-np.pi, np.pi))
        assert hist.min() > 15, f"seed {t.seed}: a side of the tree has almost no LEDs"


def test_depth_zigzags_into_branches(trees):
    for t in trees:
        y = t.positions[:, 1]
        depth = np.hypot(t.positions[:, 0], t.positions[:, 2]) / np.maximum(
            t.cone_radius_at(y), 1e-6
        )
        low = y < 0.7 * t.height  # ignore the narrow tip
        assert np.percentile(depth[low], 10) < 0.65
        assert np.percentile(depth[low], 90) > 0.85


def test_index_from_top_quirk_matches_positions(trees):
    seen = set()
    for t in trees:
        for s, pts in zip(t.strands, strand_slices(t)):
            first, last = pts[:10, 1].mean(), pts[-10:, 1].mean()
            assert (first > last) == s.index_from_top, f"seed {t.seed}"
            seen.add(s.index_from_top)
    assert seen == {True, False}, "quirk never (or always) happens across 40 seeds"


def test_layouts_occur(trees):
    assert {t.layout for t in trees} == {"interleaved", "stacked"}
    for t in trees:
        assert len({s.handedness for s in t.strands}) == 1


def test_no_quirks():
    for seed in range(1, 15):
        t = generate_tree(TreeSpec(quirks=False), seed=seed)
        assert t.layout == "interleaved"
        assert not any(s.index_from_top for s in t.strands)


# -- user-specified parameters ----------------------------------------------------------


def test_strip_length_sets_spacing():
    t = generate_tree(spec((150, 12.0), (100, 5.0)), seed=4)
    assert [s.count for s in t.strands] == [150, 100]
    assert [s.start for s in t.strands] == [0, 150]
    assert t.strands[0].spacing == pytest.approx(0.08)
    assert t.strands[1].spacing == pytest.approx(0.05)
    for s, pts in zip(t.strands, strand_slices(t)):
        gaps = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        assert gaps.max() < s.spacing + 0.018  # spacing plus jitter


def test_explicit_size_layout_and_start():
    t = generate_tree(
        spec((100, 8.0, "top"), (100, 8.0, "bottom"), height=1.2, radius=0.4,
             layout="stacked"),
        seed=2,
    )
    assert (t.height, t.radius, t.layout) == (1.2, 0.4, "stacked")
    assert [s.index_from_top for s in t.strands] == [True, False]
    lower, upper = strand_slices(t)
    assert lower[:, 1].mean() < upper[:, 1].mean()  # stacked: strip 1 below strip 2
    assert t.positions[:, 1].max() <= 1.2


def test_overriding_one_value_keeps_the_rest_of_the_seed():
    a = generate_tree(TreeSpec(), seed=8)
    b = generate_tree(TreeSpec(height=a.height), seed=8)
    assert np.allclose(a.positions, b.positions)


def test_many_strips_and_uneven_counts():
    t = generate_tree(TreeSpec.uniform(301, 3), seed=5)
    assert [s.count for s in t.strands] == [101, 100, 100]
    assert t.positions.shape == (301, 3)
    assert generate_tree(TreeSpec.uniform(50, 1), seed=5).layout == "single"


def test_short_strip_covers_less_height_with_a_warning():
    t = generate_tree(spec((60, 3.0), layout="interleaved"), seed=3)
    s = t.strands[0]
    assert 0 < s.coverage < 0.6
    assert t.positions[:, 1].max() < 0.7 * t.height
    assert len(t.warnings) == 1 and "too short" in t.warnings[0]
    gaps = np.linalg.norm(np.diff(t.positions, axis=0), axis=1)
    assert gaps.max() < 0.05 + 0.018


def test_tightly_wound_strips_warn():
    t = generate_tree(
        spec((1000, 30.0), (1000, 30.0), height=1.0, radius=0.3, layout="interleaved"), seed=1
    )
    assert any("hard to tell apart" in w for w in t.warnings)


def test_too_much_wire_is_an_error():
    with pytest.raises(SpecError, match="more than fits"):
        generate_tree(spec((2000, 900.0), height=0.5, radius=0.1), seed=1)


def test_single_led_strip():
    t = generate_tree(spec((1,), (10, 0.7)), seed=1)
    assert t.positions.shape == (11, 3)


@pytest.mark.parametrize(
    "bad, match",
    [
        (spec(), "number of strips"),
        (spec(*[(10,)] * 9), "number of strips"),
        (spec((0,)), "strip 1 LEDs"),
        (spec((200, 0.5)), "0.2 cm between LEDs"),
        (spec((10, 20.0)), "200.0 cm between LEDs"),
        (spec((10, -1.0)), "positive"),
        (spec((10, None, "middle")), "start"),
        (spec((2000,), (2000,), (2000,)), "total LEDs"),
        (spec((10,), height=0.1), "height"),
        (spec((10,), radius=9), "radius"),
        (spec((10,), layout="spiral"), "layout"),
    ],
)
def test_invalid_specs(bad, match):
    with pytest.raises(SpecError, match=match):
        generate_tree(bad, seed=1)


def test_spec_from_dict_parses_viewer_json():
    s = TreeSpec.from_dict(
        {
            "strips": [{"leds": 120, "length": 9.6, "start": "top"}, {"leds": 80.0, "length": None}],
            "height": "",
            "radius": 0.6,
            "layout": "stacked",
            "quirks": False,
            "seed": None,
        }
    )
    assert s.strips == [StripSpec(120, 9.6, "top"), StripSpec(80, None, "auto")]
    assert (s.height, s.radius, s.layout, s.quirks, s.seed) == (None, 0.6, "stacked", False, None)
    assert TreeSpec.from_dict(s.to_dict()) == s


@pytest.mark.parametrize(
    "d, match",
    [
        ([], "object"),
        ({"strips": {}}, "list"),
        ({"strips": [{"leds": 1.5}]}, "whole number"),
        ({"strips": [{"leds": "10"}]}, "whole number"),
        ({"strips": [{"leds": 10, "colour": 1}]}, "expected"),
        ({"strips": [{"leds": 10, "length": "long"}]}, "number"),
        ({"bogus": 1}, "unknown"),
        ({"quirks": "yes"}, "quirks"),
        ({"seed": -1}, "seed"),
    ],
)
def test_spec_from_dict_rejects(d, match):
    with pytest.raises(SpecError, match=match):
        TreeSpec.from_dict(d)


def test_spec_from_config():
    cfg = config_from_dict(
        {
            "led_count": 300,
            "controllers": [],
            "sim": {
                "strips": [{"leds": 100, "length": 7}, {"leds": 200, "start": "top"}],
                "height": 1.8,
                "layout": "interleaved",
                "seed": 3,
            },
        }
    )
    s = spec_from_config(cfg)
    assert s.strips == [StripSpec(100, 7, "auto"), StripSpec(200, None, "top")]
    assert (s.height, s.radius, s.layout, s.seed) == (1.8, None, "interleaved", 3)
    default = spec_from_config(config_from_dict({"led_count": 301, "controllers": []}))
    assert [st.leds for st in default.strips] == [151, 150]


# -- misc ---------------------------------------------------------------------------------


def test_split_counts():
    assert split_counts(400, 2) == [200, 200]
    assert split_counts(10, 3) == [4, 3, 3]


def test_save_load_roundtrip(tmp_path):
    t = generate_tree(spec((120, 9.0, "top"), (80,), height=1.7), seed=9)
    path = tmp_path / "sub" / "tree.json"
    t.save(path)
    loaded = SimTree.load(path)
    assert loaded.to_dict() == t.to_dict()
    assert loaded.spec == t.spec
    assert np.allclose(loaded.positions, t.positions, atol=1e-4)


def test_load_rejects_unknown_version():
    d = generate_tree(seed=9).to_dict()
    d["version"] = 1
    with pytest.raises(ValueError, match="regenerate"):
        SimTree.from_dict(d)
