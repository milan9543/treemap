import numpy as np
import pytest

from treemap.patterns import chase_frames, parse_color


@pytest.mark.parametrize(
    "text, rgb",
    [
        ("red", (255, 0, 0)),
        (" White ", (255, 255, 255)),
        ("#ff8800", (255, 136, 0)),
        ("00FF10", (0, 255, 16)),
        ("1, 2,3", (1, 2, 3)),
    ],
)
def test_parse_color(text, rgb):
    assert parse_color(text) == rgb


@pytest.mark.parametrize("text", ["purple-ish", "#ff88", "1,2", "1,2,300", "-1,0,0", ""])
def test_parse_color_rejects(text):
    with pytest.raises(ValueError):
        parse_color(text)


def test_chase_visits_every_led_in_order():
    frames = list(chase_frames(6, (200, 100, 0), width=3))
    assert [i for i, _ in frames] == list(range(6))
    for head, f in frames:
        assert f[head].tolist() == [200, 100, 0]  # head at full brightness
        assert f.max(axis=1).argmax() == head
        lit = np.flatnonzero(f.any(axis=1))
        assert lit.min() >= head - 2 and lit.max() == head  # tail only behind the head
    _, f = frames[3]
    assert f[2, 0] < 200 and f[1, 0] < f[2, 0]  # fading tail
