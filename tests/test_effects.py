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
    lit_any = False
    for k in range(60):
        frame = np.asarray(effect.render(k / 20))
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
    assert {"solid", "rainbow", "twinkle", "chase", "markers", "led"} <= {d["name"] for d in desc}
    for d in desc:
        assert d["label"] and d["description"] and d["group"]
    led = next(d for d in desc if d["name"] == "led")
    assert led["params"][0]["max"] == N - 1


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


def test_solid_and_markers():
    assert (create_effect("solid", ctx(), {"color": "blue"}).render(0) == (0, 0, 255)).all()
    f = create_effect("markers", ctx()).render(0)
    assert tuple(f[0]) == (0, 80, 255) and tuple(f[100]) == (0, 255, 0)
    assert tuple(f[50]) == (255, 0, 0) and tuple(f[10]) == (60, 60, 60) and not f[11].any()


def test_single_led_with_and_without_neighbours():
    e = create_effect("led", ctx(), {"index": 5, "color": "red"})
    f = e.render(0)
    assert tuple(f[5]) == (255, 0, 0) and f[4, 0] == f[6, 0] == pytest.approx(25.5)
    e.set_params({"neighbours": False})
    assert np.count_nonzero(e.render(0).any(axis=1)) == 1


def test_chase_moves_forward():
    e = create_effect("chase", ctx(), {"speed": 10, "width": 1})
    heads = [int(np.argmax(e.render(t).max(axis=1))) for t in (0, 0.5, 1.0)]
    assert heads == [0, 5, 10]


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


def test_hsv_to_rgb_primaries():
    rgb = hsv_to_rgb(np.array([0, 1 / 3, 2 / 3, 1.0]))
    assert np.allclose(rgb, [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 0, 0]])
