import numpy as np
import pytest
from typer.testing import CliRunner

from treemap.cameras.sim import SimCamera
from treemap.cli import app
from treemap.mapping.model import TreeMap
from treemap.outputs.base import LedOutput
from treemap.scan.capture import load_scans, scan_angle
from treemap.scan.cleanup import cleanup
from treemap.scan.evaluate import evaluate
from treemap.scan.reconstruct import build_map
from treemap.sim.tree import TreeSpec, generate_tree


class FrameOutput(LedOutput):
    def __init__(self, n):
        super().__init__(n)
        self.last_frame = np.zeros((n, 3), np.uint8)

    def _show(self, colors):
        self.last_frame = colors.copy()


@pytest.mark.parametrize("seed", [11, 12])
def test_reconstruction_within_2_percent_of_height(seed, tmp_path):
    tree = generate_tree(TreeSpec.uniform(200, 2, seed=seed))
    out = FrameOutput(tree.led_count)
    cam = SimCamera(tree, lambda: out.last_frame)
    for angle in (0, 90, 180, 270):
        cam.set_angle(angle)
        scan_angle(out, cam, angle, tmp_path, settle_s=0, flash_s=0)

    tree_map, _ = build_map(load_scans(tmp_path), tree.led_count)
    tree_map.save(tmp_path / "map.json")
    ev = evaluate(TreeMap.load(tmp_path / "map.json"), tree)
    assert ev.summary()["median"] < 0.02
    assert ev.summary("ok")["p95"] < 0.02
    assert tree_map.counts()["ok"] > 0.9 * tree.led_count


def test_cleanup_flags_outliers_gaps_and_breaks():
    t = np.arange(100) * 0.07  # a helix with 7 cm between LEDs, then a second strip
    helix = np.stack([0.5 * np.cos(t / 0.5), t * 0.1, 0.5 * np.sin(t / 0.5)], axis=1)
    P = np.concatenate([helix[:60], helix[60:] + [3.0, 0, 0]])  # break between 59 and 60
    truth = P.copy()
    P[20] += [0.6, 0.3, 0]  # a reflection
    P[30:32] = np.nan  # short gap
    P[40:48] = np.nan  # long gap

    out, status, info = cleanup(P)
    assert info["outliers"] == [20]
    assert status[20] == status[30] == status[31] == "interpolated"
    assert np.linalg.norm(out[20] - truth[20]) < 0.02
    assert set(status[40:48]) == {"failed"}
    assert status[59] == status[60] == "ok"  # a strip break is not an outlier


def test_cli_reconstruct_and_evaluate(tmp_path, write_config):
    write_config("led_count: 120\ncontrollers: []\nsim: {seed: 4, port: 1}\n")
    runner = CliRunner()
    for args in (["scan", "--flash", "0"], ["reconstruct"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
    assert "ok" in result.output
    assert TreeMap.load(tmp_path / "data/tree_map.json").led_count == 120

    result = runner.invoke(app, ["sim", "evaluate"])
    assert result.exit_code == 0, result.output
    assert "all" in result.output and "cm" in result.output


def test_cli_reconstruct_without_scans():
    result = CliRunner().invoke(app, ["reconstruct"])
    assert result.exit_code == 1
    assert "at least two view angles" in result.output
