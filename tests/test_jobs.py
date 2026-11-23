import numpy as np
import pytest

from tests.walk_render import walk_round
from treemap.cameras.http import HttpCamera
from treemap.config import config_from_dict
from treemap.jobs import JobRejected, Jobs
from treemap.mapping.model import TreeMap
from treemap.outputs.base import LedOutput
from treemap.sim.tree import generate_tree


class Dark(LedOutput):
    def _show(self, colors: np.ndarray) -> None:
        pass


@pytest.fixture
def setup(tmp_path):
    tree = generate_tree(seed=3)
    cfg = config_from_dict({})
    cfg.base_dir, cfg.led_count = tmp_path, tree.led_count
    jobs = Jobs(cfg, lambda: Dark(tree.led_count), HttpCamera(), "test phone")
    return cfg, tree, jobs


def run(jobs, kind, params=None, timeout=60):
    jobs.start(kind, params)
    assert jobs.wait(timeout)
    return jobs.state()


def test_reconstruct_and_ignoring_an_leds_readings(setup):
    cfg, tree, jobs = setup
    walk_round(tree).save(cfg.scan_dir / "round_01.npz")
    st = run(jobs, "reconstruct")
    assert st["status"] == "done" and st["result"]["counts"]["ok"] > 300, st

    ok = TreeMap.load(cfg.map_path).indices("ok")[3]
    assert run(jobs, "interpolate", {"index": ok})["result"]["status"] == "interpolated"
    assert run(jobs, "measure", {"index": ok})["result"]["status"] == "ok"


def test_rejections(setup):
    _, _, jobs = setup
    for kind, params in (("nope", {}), ("evaluate", {}), ("scan", {"rounds": 0}),
                         ("interpolate", {"index": -1}), ("scan", {"camera": "a phone"})):
        with pytest.raises(JobRejected):
            jobs.start(kind, params)
