import json
import time
import urllib.request

import pytest
from websockets.sync.client import connect

from treemap.cameras.sim import SimCamera
from treemap.config import config_from_dict
from treemap.jobs import JobRejected, Jobs
from treemap.mapping.model import TreeMap
from treemap.outputs.sim import SimOutput
from treemap.sim.server import ServerThread, SimServer
from treemap.workflow import ensure_sim_tree


@pytest.fixture
def cfg(tmp_path):
    c = config_from_dict({"led_count": 60, "controllers": [], "sim": {"seed": 3, "port": 1}})
    c.base_dir = tmp_path
    ensure_sim_tree(c)
    return c


def make_jobs(cfg, **kw):
    states = []
    jobs = Jobs(cfg, lambda: SimOutput(cfg.led_count, port=1), on_change=states.append, **kw)
    return jobs, states


def run(jobs, kind, params=None, timeout=60):
    jobs.start(kind, params)
    assert jobs.wait(timeout)
    return jobs.state()


def test_scan_reconstruct_and_fix_jobs(cfg):
    jobs, states = make_jobs(cfg)
    st = run(jobs, "scan", {"angles": [0, 90, 180, 270], "flash": 0})
    assert st["status"] == "done", st
    assert [a["angle"] for a in st["angles"]] == [0, 90, 180, 270]
    assert st["result"]["coverage"]["two_plus"] > 50
    assert any(s["progress"] for s in states)  # progress was reported

    st = run(jobs, "reconstruct")
    assert st["status"] == "done" and st["result"]["counts"]["ok"] > 50

    ok = TreeMap.load(cfg.map_path).indices("ok")[3]
    assert run(jobs, "interpolate", {"index": ok})["result"]["status"] == "interpolated"
    assert run(jobs, "measure", {"index": ok})["result"]["status"] == "ok"
    assert run(jobs, "evaluate")["result"]["rows"][-1]["median"] < 0.02


def test_rejections_and_cancel(cfg):
    jobs, _ = make_jobs(cfg)
    for kind, params in (("nope", {}), ("scan", {"leds": "70"}), ("rescan", {"index": -1})):
        with pytest.raises(JobRejected):
            jobs.start(kind, params)

    def stop_after_5(angle, done, total, i, entry):
        if done == 5:
            jobs.cancel()
        jobs._check_cancel()

    jobs._on_progress = stop_after_5
    jobs.start("scan", {"angles": [0], "flash": 0})
    with pytest.raises(JobRejected, match="already running"):
        jobs.start("reconstruct")
    jobs.wait(30)
    assert jobs.state()["status"] == "cancelled"
    saved = json.loads((cfg.scan_dir / "angle_000.json").read_text())
    assert len(saved["leds"]) == 5  # progress kept


def test_job_waits_for_the_user_to_move_the_camera(cfg, monkeypatch):
    monkeypatch.setattr(SimCamera, "set_angle", lambda self, a: False)
    jobs, _ = make_jobs(cfg)
    jobs.start("scan", {"angles": [0], "leds": "0-2", "flash": 0})
    deadline = time.monotonic() + 5
    while jobs.state()["status"] != "waiting" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert "Point the camera at 0°" in jobs.state()["prompt"]
    jobs.proceed()
    assert jobs.wait(30) and jobs.state()["status"] == "done"


def test_server_runs_jobs_and_serves_scans(cfg):
    from treemap.cli import _make_engine, _make_jobs

    srv = SimServer(tree_path=cfg.sim_tree_path, map_path=cfg.map_path, port=0,
                    led_count=cfg.led_count, cfg=cfg,
                    make_engine=lambda s: _make_engine(cfg, sim_port=s.port),
                    make_jobs=lambda s: _make_jobs(cfg, s))
    with ServerThread(srv), connect(f"ws://127.0.0.1:{srv.port}/ws/viewer") as ws:
        ws.send(json.dumps({"type": "job.start", "job": "scan",
                            "params": {"angles": [0, 180], "leds": "0-29", "flash": 0}}))
        ws.send(json.dumps({"type": "effect.run", "effect": "rainbow", "params": {}}))
        refused, final = None, None
        deadline = time.monotonic() + 60
        while final is None and time.monotonic() < deadline:
            msg = ws.recv(timeout=5)
            if isinstance(msg, bytes):
                continue
            d = json.loads(msg)
            if d["type"] == "effect.error":
                refused = d["error"]
            elif d["type"] == "job" and d["status"] in ("done", "error", "cancelled"):
                final = d
        assert final["status"] == "done", final
        assert refused and "using the LEDs" in refused

        base = f"http://127.0.0.1:{srv.port}"
        scans = json.load(urllib.request.urlopen(base + "/api/scans"))
        assert [s["angle"] for s in scans] == [0, 180]
        assert len(scans[0]["leds"]) == 30
        image = scans[0]["images"]["debug"]["name"]
        assert urllib.request.urlopen(f"{base}/api/scan-image/{image}").read()[:4] == b"\x89PNG"
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{base}/api/scan-image/angle_000.json")
