import json

import numpy as np
import pytest
import yaml
from typer.testing import CliRunner
from websockets.sync.client import connect

from treemap import __version__
from treemap.cli import app
from treemap.sim.server import ServerThread, SimServer

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "config" in result.output


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_does_not_load_a_broken_config(write_config):
    write_config("output: dmx\n")
    assert runner.invoke(app, ["--help"]).exit_code == 0
    assert runner.invoke(app, ["config", "--help"]).exit_code == 0


def test_config_show_defaults():
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert "built-in defaults" in result.output
    body = yaml.safe_load(result.output)
    assert body["led_count"] == 400
    assert body["output"] == "sim"


def test_config_show_with_file(write_config):
    path = write_config("led_count: 200\ncontrollers: []\n", name="custom.yaml")
    result = runner.invoke(app, ["--config", str(path), "config", "show"])
    assert result.exit_code == 0, result.output
    assert str(path) in result.output
    assert yaml.safe_load(result.output)["led_count"] == 200


def test_sim_new_saves_tree(tmp_path):
    result = runner.invoke(app, ["sim", "new", "--seed", "42"])
    assert result.exit_code == 0, result.output
    assert "seed 42" in result.output
    data = json.loads((tmp_path / "data" / "sim_tree.json").read_text())
    assert data["seed"] == 42 and data["led_count"] == 400
    assert len(data["strands"]) == 2


def test_sim_new_uses_config_section(tmp_path, write_config):
    write_config(
        "led_count: 90\ncontrollers: []\n"
        "sim:\n  seed: 5\n  quirks: false\n  height: 1.6\n"
        "  strips:\n    - {leds: 60, length: 4.2}\n    - {leds: 30}\n"
    )
    result = runner.invoke(app, ["sim", "new"])
    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / "data" / "sim_tree.json").read_text())
    assert data["seed"] == 5 and data["led_count"] == 90 and data["height"] == 1.6
    assert [s["count"] for s in data["strands"]] == [60, 30]
    assert data["strands"][0]["spacing"] == pytest.approx(0.07)
    assert not any(s["index_from_top"] for s in data["strands"])
    assert "too short to spiral" in result.output  # 4.2 m doesn't reach the top


def test_sim_new_strip_options_override_config(tmp_path):
    result = runner.invoke(
        app,
        ["sim", "new", "--seed", "3", "--strip", "100:8:top", "--strip", "50",
         "--strip", "50:4", "--radius", "0.7", "--layout", "stacked"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / "data" / "sim_tree.json").read_text())
    assert [s["count"] for s in data["strands"]] == [100, 50, 50]
    assert data["strands"][0]["index_from_top"] is True
    assert data["strands"][2]["spacing"] == pytest.approx(0.08)
    assert (data["radius"], data["layout"]) == (0.7, "stacked")
    assert "strip 3: LEDs 150-199, 4.0 m (8.0 cm spacing)" in result.output


def test_sim_new_warns_when_led_count_differs(tmp_path):
    result = runner.invoke(app, ["sim", "new", "--seed", "1", "--strip", "300"])
    assert result.exit_code == 0, result.output
    assert "the tree has 300 LEDs but led_count in the config is 400" in result.output


@pytest.mark.parametrize(
    "args, match",
    [
        (["--strip", "lots"], "LEDS"),
        (["--strip", "200:0.5"], "cm between LEDs"),
        (["--layout", "spiral"], "layout must be"),
        (["--strip", "2000:900", "--height", "0.5", "--radius", "0.1"], "more than fits"),
    ],
)
def test_sim_new_bad_options(args, match):
    result = runner.invoke(app, ["sim", "new", "--seed", "1", *args])
    assert result.exit_code == 2
    assert match in result.output


@pytest.fixture
def viewer(tmp_path, write_config):
    """A running sim server, with config.yaml pointing SimOutput at it."""
    srv = SimServer(tree_path=tmp_path / "t.json", map_path=tmp_path / "m.json", port=0)
    with ServerThread(srv):
        write_config(f"led_count: 12\ncontrollers: []\nsim:\n  port: {srv.port}\n")
        with connect(f"ws://127.0.0.1:{srv.port}/ws/viewer") as ws:
            ws.recv(timeout=5)  # status message
            yield ws


def frames_from(ws):
    frames = []
    while True:
        try:
            msg = ws.recv(timeout=0.3)
        except TimeoutError:
            return frames
        if isinstance(msg, bytes):
            frames.append(np.frombuffer(msg, dtype=np.uint8).reshape(-1, 3))


def test_chase_runs_through_every_led(viewer):
    result = runner.invoke(app, ["test", "chase", "--fps", "200", "--width", "1"])
    assert result.exit_code == 0, result.output
    assert "LED   11 / 11" in result.output
    frames = frames_from(viewer)
    heads = [int(f.max(axis=1).argmax()) for f in frames if f.any()]
    assert heads == list(range(12))
    assert not frames[-1].any()  # turned off at the end


def test_led_lights_one_then_turns_off(viewer):
    result = runner.invoke(app, ["test", "led", "7", "--color", "red", "--seconds", "0.05"])
    assert result.exit_code == 0, result.output
    frames = frames_from(viewer)
    assert frames[0][7].tolist() == [255, 0, 0] and frames[0].sum() == 255
    assert not frames[-1].any()


def test_all_white_and_off(viewer):
    result = runner.invoke(app, ["test", "all-white", "--level", "50", "--seconds", "0"])
    assert result.exit_code == 0, result.output
    assert (frames_from(viewer)[0] == 50).all()
    assert runner.invoke(app, ["test", "off"]).exit_code == 0
    assert not frames_from(viewer)[-1].any()


def test_led_index_out_of_range(write_config):
    write_config("led_count: 12\ncontrollers: []\n")
    result = runner.invoke(app, ["test", "led", "12"])
    assert result.exit_code == 2
    assert "below led_count" in result.output


def test_bad_color():
    result = runner.invoke(app, ["test", "led", "1", "--color", "nope", "--seconds", "0"])
    assert result.exit_code == 2
    assert "can't parse colour" in result.output


def test_effects_lists_effects_and_params():
    result = runner.invoke(app, ["effects"])
    assert result.exit_code == 0, result.output
    assert "rainbow" in result.output and "Diagnostics" in result.output
    assert "speed=0.15" in result.output


def test_run_streams_effect_then_turns_off(viewer, write_config):
    result = runner.invoke(
        app, ["run", "solid", "-p", "color=0,0,255", "--seconds", "0.3", "--brightness", "1"]
    )
    assert result.exit_code == 0, result.output
    frames = frames_from(viewer)
    assert any((f == (0, 0, 255)).all() for f in frames)
    assert not frames[-1].any()


@pytest.mark.parametrize(
    "args, match",
    [
        (["disco"], "unknown effect"),
        (["solid", "-p", "colour=red"], "no parameter"),
        (["solid", "-p", "color"], "key=value"),
        (["rainbow", "-p", "speed=99"], "outside"),
    ],
)
def test_run_rejects_bad_requests(args, match):
    result = runner.invoke(app, ["run", *args, "--seconds", "0.1"])
    assert result.exit_code == 2
    assert match in result.output


def test_wled_output_not_ready_yet(write_config):
    write_config("output: wled\n")
    result = runner.invoke(app, ["test", "off"])
    assert result.exit_code == 1
    assert "Batch 8" in result.output


def test_config_show_reports_errors(write_config):
    write_config("output: dmx\n")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 2
    assert "output must be one of" in result.output
