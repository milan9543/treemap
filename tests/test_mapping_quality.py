import os

import numpy as np
import pytest
from typer.testing import CliRunner

from treemap.cli import app
from treemap.config import ConfigError, config_from_dict
from treemap.effects import EffectContext, ParamError, create_effect
from treemap.mapping.model import MapFile, TreeMap
from treemap.mapping.quality import STATUS_COLORS, fix_frame, status_frame, verify_frames


def small_map():
    y = np.linspace(0, 1, 5)
    P = np.stack([np.linspace(-0.4, 0.4, 5), y, np.zeros(5)], axis=1)
    P[4] = np.nan
    status = np.array(["ok", "ok", "interpolated", "ok", "failed"])
    return TreeMap(P, status)


def test_status_and_fix_frames():
    frame = status_frame(small_map())
    assert tuple(frame[0]) == STATUS_COLORS["ok"]
    assert tuple(frame[2]) == STATUS_COLORS["interpolated"]
    assert tuple(frame[4]) == STATUS_COLORS["failed"]

    frame = fix_frame(10, 5)
    assert frame[5, 2] > frame[5, 0]  # blue
    assert frame[4].max() > frame[3].max() > 0 and not frame[2].any()


def test_verify_plane_rises_then_sweeps():
    frames = [f for _, f in verify_frames(small_map(), fps=20, seconds=1)]
    rise, sweep = frames[:20], frames[20:40]
    first_lit = [next(k for k, f in enumerate(rise) if f[i].any()) for i in range(4)]
    assert first_lit == sorted(first_lit) and first_lit[0] < first_lit[3]
    assert not any(f[4].any() for f in frames)  # no position: never lit
    assert any(f[0].any() for f in sweep)
    assert not frames[-1].any()


def test_hidden_leds_show_yellow_and_red_and_fix(tmp_path, write_config):
    write_config(
        "led_count: 120\ncontrollers: []\n"
        "sim: {seed: 4, port: 1, hidden_leds: '30, 60-66'}\n"
    )
    runner = CliRunner()
    for args in (["scan", "--flash", "0"], ["reconstruct"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
    tree_map = TreeMap.load(tmp_path / "data/tree_map.json")
    assert tree_map.status[30] == "interpolated"
    assert set(tree_map.status[60:67]) == {"failed"}
    assert tree_map.counts()["ok"] > 100

    result = runner.invoke(app, ["show-mapping", "--seconds", "0"])
    assert result.exit_code == 0, result.output
    assert "red: 60-66" in result.output

    ok = tree_map.indices("ok")[5]
    result = runner.invoke(app, ["fix", str(ok), "--action", "interpolate"])
    assert result.exit_code == 0, result.output
    assert f"LED {ok} is now interpolated" in result.output

    result = runner.invoke(app, ["fix", str(ok), "--action", "rescan", "--angle", "0",
                                 "--angle", "90"])
    assert result.exit_code == 0, result.output
    assert f"LED {ok} is now ok" in result.output


def test_mapping_effects_follow_the_map_file(tmp_path):
    path = tmp_path / "tree_map.json"
    ctx = EffectContext(n=5, tree_map=MapFile(path))
    with pytest.raises(ParamError, match="no tree map"):
        create_effect("map-status", ctx)

    small_map().save(path)
    effect = create_effect("map-status", ctx)
    assert tuple(effect.render(0)[2]) == STATUS_COLORS["interpolated"]

    changed = small_map()
    changed.status[2] = "ok"
    changed.save(path)
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 10**9))  # make sure the stamp changes
    assert tuple(effect.render(0.1)[2]) == STATUS_COLORS["ok"]


def test_hidden_leds_validated():
    with pytest.raises(ConfigError, match="hidden_leds"):
        config_from_dict({"led_count": 10, "controllers": [], "sim": {"hidden_leds": "5-20"}})
