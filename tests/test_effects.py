import numpy as np
import pytest

from treemap.effects import (
    EffectContext,
    Param,
    ParamError,
    create_effect,
    describe_effects,
    effect_names,
    get_effect,
)
from treemap.effects.base import hsv_to_rgb
from treemap.mapping.model import TreeMap

N = 120


def _helix_map(n):
    t = np.linspace(0, 1, n)
    P = np.stack([0.3 * (1 - t) * np.cos(30 * t), t, 0.3 * (1 - t) * np.sin(30 * t)], axis=1)
    status = np.array(["ok"] * n, dtype="<U12")
    status[::7] = "interpolated"
    return TreeMap(P, status)


def ctx(n=N, seed=1):
    tree_map = _helix_map(n)
    return EffectContext(n=n, rng=np.random.default_rng(seed), tree_map=lambda: tree_map)


@pytest.mark.parametrize("name", effect_names())
def test_every_effect_renders_valid_frames(name):
    effect = create_effect(name, ctx())
    sparkly = create_effect(name, ctx(), {"sparkle": True}) if effect.sparkles else effect
    lit_any = False
    for k in range(60):
        frame = np.asarray(effect.render(k / 20))
        assert np.isfinite(sparkly.frame(k / 20)).all()
        assert frame.shape == (N, 3), name
        assert np.isfinite(frame).all()
        assert frame.min() >= 0 and frame.max() <= 255.5
        lit_any |= bool(frame.max() > 0)
    assert lit_any, f"{name} never lights anything"


@pytest.mark.parametrize("name", effect_names())
def test_every_effect_accepts_its_own_described_values(name):
    cls = get_effect(name)
    desc = cls.describe(N)
    values = {p["name"]: p["default"] for p in desc["params"]}
    effect = cls(ctx(), **values)  # defaults round-trip through JSON form
    assert effect.param_values() == values
    for p in desc["params"]:  # and the extremes are accepted
        if p["min"] is not None:
            effect.set_params({p["name"]: p["min"]})
            effect.set_params({p["name"]: p["max"]})
            effect.render(0.5)


def test_descriptions_are_complete():
    desc = describe_effects(N)
    assert {"solid", "rainbow", "twinkle", "plane"} <= {d["name"] for d in desc}
    for d in desc:
        assert d["label"] and d["description"] and d["group"] in ("Classic", "3D")


def test_param_parsing():
    color = Param("c", "color", (0, 0, 0))
    assert color.parse("red", N) == (255, 0, 0)
    assert color.parse("#00ff10", N) == (0, 255, 16)
    assert color.parse([1, 2, 3], N) == (1, 2, 3)
    num = Param("x", "float", 1.0, min=0, max=2)
    assert num.parse("1.5", N) == 1.5
    integer = Param("i", "int", 1, min=0, max=10)
    assert integer.parse("4", N) == 4 and integer.parse(4.0, N) == 4
    flag = Param("b", "bool", False)
    assert flag.parse("yes", N) is True and flag.parse(False, N) is False
    choice = Param("m", "choice", "a", choices=("a", "b"))
    assert choice.parse("b", N) == "b"


@pytest.mark.parametrize(
    "param, value, match",
    [
        (Param("x", "float", 1.0, min=0, max=2), 3, "outside"),
        (Param("x", "float", 1.0), "fast", "invalid float"),
        (Param("x", "float", 1.0), True, "invalid float"),
        (Param("i", "int", 1), 1.5, "invalid int"),
        (Param("c", "color", (0, 0, 0)), "nope", "#rrggbb"),
        (Param("c", "color", (0, 0, 0)), [1, 2, 300], "invalid color"),
        (Param("m", "choice", "a", choices=("a", "b")), "c", "one of a, b"),
        (Param("b", "bool", False), "maybe", "invalid bool"),
        (Param("i", "int", 0, min=0, max_is_last_led=True), N, "outside"),
    ],
)
def test_param_rejects(param, value, match):
    with pytest.raises(ParamError, match=match):
        param.parse(value, N)


def test_unknown_param_and_bad_value_change_nothing():
    effect = create_effect("rainbow", ctx(), {"speed": 0.5})
    with pytest.raises(ParamError, match="no parameter 'nope'"):
        effect.set_params({"speed": 1.0, "nope": 1})
    with pytest.raises(ParamError):
        effect.set_params({"speed": 1.0, "repeats": -5})
    assert effect.p["speed"] == 0.5


def test_unknown_effect():
    with pytest.raises(KeyError, match="unknown effect"):
        create_effect("disco", ctx())


def test_solid():
    assert (create_effect("solid", ctx(), {"color": "blue"}).render(0) == (0, 0, 255)).all()


def test_wipe_fills_then_empties():
    e = create_effect("wipe", ctx(n=10), {"speed": 10, "color": "red"})
    assert np.count_nonzero(e.render(0.5)[:, 0]) == 5
    assert np.count_nonzero(e.render(0.999)[:, 0]) == 10
    assert np.count_nonzero(e.render(1.5)[:, 0]) == 5  # second colour (black) half way


def test_rainbow_spans_hues():
    f = create_effect("rainbow", ctx(), {"repeats": 1}).render(0)
    assert tuple(np.round(f[0])) == (255, 0, 0)
    assert f[N // 3, 1] > 200 and f[2 * N // 3, 2] > 200  # green then blue


def test_twinkle_is_reproducible_with_a_seed_and_fades():
    a = create_effect("twinkle", ctx(seed=3), {"rate": 50})
    b = create_effect("twinkle", ctx(seed=3), {"rate": 50})
    for t in np.arange(0, 2, 0.05):
        assert np.array_equal(a.render(t), b.render(t))
    a.set_params({"rate": 0.1})
    for t in np.arange(2, 8, 0.05):
        last = a.render(t)
    assert last.max() < 60  # earlier twinkles faded out


def test_a_custom_palette_and_one_that_is_gone():
    custom = {"my-00000001": [(0, 0, 255)]}
    c = ctx()
    c.palettes = custom.get
    e = create_effect("rainbow3d", c, {"palette": "my-00000001"})
    frame = e.render(0.3)
    assert np.allclose(frame[frame.any(axis=1)], (0, 0, 255))
    e.set_params({"palette": "my-0000dead"})  # deleted: the default palette
    assert np.array_equal(e.render(0.3), create_effect("rainbow3d", c).render(0.3))


def test_old_settings_carry_over():
    old = {"color": "gold", "mixed": True, "background": "off", "nope": 1}
    new = get_effect("ripple").upgrade(old, N, old=True)
    assert new == {"color": "#ff8c00", "colors": "palette", "palette": "christmas",
                   "background": "#000000", "background_level": 1.0}


def test_sparkles_over_an_effect():
    plain = create_effect("solid", ctx(), {"color": "#400000"})
    assert np.array_equal(plain.frame(0.5), plain.render(0.5))  # off: just the effect
    e = create_effect("solid", ctx(), {"color": "#400000", "sparkle": True, "sparkle_rate": 50})
    lit = np.zeros(N, bool)
    for k in range(40):
        frame = e.frame(k / 20)
        lit |= frame.min(axis=1) > 0x40  # white twinkles brighten the dark red
    assert 10 < lit.sum() < N
    assert "sparkle" not in {p.name for p in get_effect("twinkle").params}


def test_hsv_to_rgb_primaries():
    rgb = hsv_to_rgb(np.array([0, 1 / 3, 2 / 3, 1.0]))
    assert np.allclose(rgb, [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 0, 0]])
