import json

import numpy as np
import pytest
from typer.testing import CliRunner

from treemap.cameras.sim import SimCamera, _splat
from treemap.cli import app
from treemap.outputs.base import LedOutput
from treemap.scan.capture import AngleScan, load_scans, parse_leds, scan_angle
from treemap.scan.detect import detect
from treemap.sim.tree import TreeSpec, generate_tree


class FrameOutput(LedOutput):
    """Keeps the last frame for the sim camera and counts frames shown."""

    def __init__(self, n):
        super().__init__(n)
        self.last_frame = np.zeros((n, 3), np.uint8)
        self.shown = 0

    def _show(self, colors):
        self.last_frame = colors.copy()
        self.shown += 1


class CountingCamera(SimCamera):
    captures = 0

    def _capture(self):
        self.captures += 1
        return super()._capture()


@pytest.fixture
def rig():
    tree = generate_tree(TreeSpec.uniform(60, 2, seed=3))
    out = FrameOutput(tree.led_count)
    return tree, out, CountingCamera(tree, lambda: out.last_frame)


def test_detect_finds_blob_with_subpixel_accuracy():
    rng = np.random.default_rng(0)
    dark = np.clip(rng.normal(15, 2.5, (120, 160, 3)), 0, 255).astype(np.uint8)
    assert detect(dark, dark) is None

    img = dark.astype(np.float32)
    _splat(img, 70.3, 41.6, 1.8, np.full(3, 400.0))
    d = detect(np.clip(img, 0, 255).astype(np.uint8), dark)
    assert d is not None
    assert abs(d.u - 70.3) < 0.2 and abs(d.v - 41.6) < 0.2
    assert d.confidence > 0.8

    _splat(img, 20.0, 90.0, 2.0, np.full(3, 150.0))  # a reflection elsewhere
    d2 = detect(np.clip(img, 0, 255).astype(np.uint8), dark)
    assert abs(d2.u - 70.3) < 0.2  # still the brighter blob
    assert d2.confidence < d.confidence


def test_sim_camera_angle_convention(rig):
    tree, out, _ = rig
    cam = SimCamera(tree, lambda: out.last_frame, clean=True)  # exact angles and aim
    pts = np.array([[0, 1, 0], [0.3, 1, 0], [0, 1, 0.3]], dtype=float)
    uv0, _ = cam.project(pts, 0)
    uv90, _ = cam.project(pts, 90)
    # θ = 0: +X is to the right; θ = 90: +Z is to the right (u ∝ X cos θ + Z sin θ)
    assert uv0[1, 0] > uv0[0, 0] + 10 and abs(uv0[2, 0] - uv0[0, 0]) < 1
    assert uv90[2, 0] > uv90[0, 0] + 10 and abs(uv90[1, 0] - uv90[0, 0]) < 1
    assert uv0[0, 1] < cam.height / 2  # 1 m up is above the camera's eye line


def test_scan_four_angles(rig, tmp_path):
    tree, out, cam = rig
    for angle in (0, 90, 180, 270):
        cam.set_angle(angle)
        scan = scan_angle(out, cam, angle, tmp_path, settle_s=0, flash_s=0)
        assert len(scan.leds) == tree.led_count
        uv, _ = cam.project(tree.positions)
        ok = scan.ok_indices()
        assert len(ok) > 0.75 * tree.led_count
        err = [np.hypot(scan.leds[i]["u"] - uv[i, 0], scan.leds[i]["v"] - uv[i, 1]) for i in ok]
        assert np.median(err) < 1.5  # the sim shifts each glow ~0.8 px per view
        for suffix in (".json", "_dark.png", "_exposure.png", "_debug.png"):
            assert (tmp_path / f"angle_{angle:03d}{suffix}").exists()
    assert [s.angle for s in load_scans(tmp_path)] == [0, 90, 180, 270]


def test_scan_resumes_and_rescans_subset(rig, tmp_path):
    tree, out, cam = rig

    class Stop(Exception):
        pass

    def stop_after_20(done, total, i, entry):
        if done == 20:
            raise Stop

    with pytest.raises(Stop):
        scan_angle(out, cam, 0, tmp_path, settle_s=0, flash_s=0, on_progress=stop_after_20)
    assert len(AngleScan.load(tmp_path / "angle_000.json").leds) == 20
    assert not out.last_frame.any()  # LEDs turned off on interruption

    cam.captures = 0
    scan = scan_angle(out, cam, 0, tmp_path, settle_s=0, flash_s=0)
    assert len(scan.leds) == tree.led_count
    assert cam.captures == 1 + tree.led_count - 20  # dark + only the remaining LEDs

    scan.leds[5]["confidence"] = scan.leds[7]["confidence"] = -1.0  # sentinels
    scan.save(tmp_path / "angle_000.json")
    cam.captures = 0
    scan = scan_angle(out, cam, 0, tmp_path, leds=[5, 6], settle_s=0, flash_s=0)
    assert cam.captures == 3
    assert scan.leds[5]["confidence"] >= 0  # rescanned
    assert scan.leds[7]["confidence"] == -1.0  # kept


def test_parse_leds():
    assert parse_leds("3-5, 9,1", 10) == [1, 3, 4, 5, 9]
    for bad in ("5-3", "10", "a-b", ""):
        with pytest.raises(ValueError):
            parse_leds(bad, 10)


def test_cli_scan(tmp_path, write_config):
    write_config("led_count: 40\ncontrollers: []\nsim: {seed: 5, port: 1}\n")
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--angle", "0", "--angle", "180", "--leds", "0-9",
                                 "--flash", "0"])
    assert result.exit_code == 0, result.output
    assert "2 angle(s)" in result.output
    data = json.loads((tmp_path / "data/scans/default/angle_180.json").read_text())
    assert sorted(map(int, data["leds"])) == list(range(10))
