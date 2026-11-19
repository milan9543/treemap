import json
import threading
import time
import urllib.request

import cv2
import numpy as np
import pytest
from websockets.sync.client import connect

from tests.walk_render import render, walk_pose, walk_round
from treemap.cameras.browser import pack_frame
from treemap.config import config_from_dict
from treemap.jobs import JobRejected, Jobs
from treemap.mapping.model import TreeMap
from treemap.outputs.sim import SimOutput
from treemap.sim.server import ServerThread, SimServer
from treemap.sim.tree import SimTree
from treemap.workflow import ensure_sim_tree


@pytest.fixture
def cfg(tmp_path):
    c = config_from_dict({"led_count": 400, "controllers": [], "sim": {"seed": 3, "port": 1}})
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


def test_reconstruct_fix_and_evaluate_jobs(cfg):
    walk_round(SimTree.load(cfg.sim_tree_path)).save(cfg.scan_dir / "round_01.npz")
    jobs, _ = make_jobs(cfg)
    st = run(jobs, "reconstruct")
    assert st["status"] == "done" and st["result"]["counts"]["ok"] > 300, st

    ok = TreeMap.load(cfg.map_path).indices("ok")[3]
    assert run(jobs, "interpolate", {"index": ok})["result"]["status"] == "interpolated"
    assert run(jobs, "measure", {"index": ok})["result"]["status"] == "ok"
    assert run(jobs, "evaluate")["result"]["rows"][-1]["median"] < 0.02


def test_rejections_and_missing_camera(cfg):
    jobs, _ = make_jobs(cfg)
    for kind, params in (("nope", {}), ("scan", {"rounds": 0}), ("interpolate", {"index": -1})):
        with pytest.raises(JobRejected):
            jobs.start(kind, params)
    st = run(jobs, "scan", {}, timeout=10)  # no viewer on port 1
    assert st["status"] == "error" and "isn't reachable" in st["error"]


def fake_phone(port: int, tree: SimTree, stop: threading.Event) -> None:
    """Plays the viewer: renders the LEDs it's sent and streams the photos back."""
    colours = [None]

    def listen(ws):
        try:
            for msg in ws:
                if isinstance(msg, bytes):
                    colours[0] = np.frombuffer(msg, np.uint8).reshape(-1, 3)
        except Exception:  # noqa: BLE001 - closed at the end of the test
            pass

    with connect(f"ws://127.0.0.1:{port}/ws/viewer") as viewer, \
            connect(f"ws://127.0.0.1:{port}/ws/camera?role=phone") as phone:
        threading.Thread(target=listen, args=(viewer,), daemon=True).start()
        t0 = time.monotonic()
        while not stop.is_set():
            t = time.monotonic() - t0
            if colours[0] is not None and len(colours[0]) == tree.led_count:
                eye, R = walk_pose(t, tree.height, lap_s=6.0)
                img, _ = render(tree.positions, colours[0], eye, R)
                jpg = cv2.imencode(".jpg", img)[1].tobytes()
                phone.send(pack_frame({"t": t, "fov_v": 55.0}, jpg))
            time.sleep(1 / 24)


def test_server_scan_job_with_a_phone(cfg):
    from treemap.cli import _make_engine, _make_jobs

    cfg.scan.round_s, cfg.scan.status_s = 7.0, 0.5
    tree = SimTree.load(cfg.sim_tree_path)
    srv = SimServer(tree_path=cfg.sim_tree_path, map_path=cfg.map_path, port=0,
                    led_count=cfg.led_count, cfg=cfg,
                    make_engine=lambda s: _make_engine(cfg, sim_port=s.port),
                    make_jobs=lambda s: _make_jobs(cfg, s))
    stop = threading.Event()
    with ServerThread(srv), connect(f"ws://127.0.0.1:{srv.port}/ws/viewer") as ws:
        phone = threading.Thread(target=fake_phone, args=(srv.port, tree, stop), daemon=True)
        phone.start()
        ws.send(json.dumps({"type": "job.start", "job": "scan", "params": {"rounds": 1}}))
        ws.send(json.dumps({"type": "effect.run", "effect": "rainbow", "params": {}}))
        refused, final, detections = None, None, 0
        deadline = time.monotonic() + 60
        while final is None and time.monotonic() < deadline:
            msg = ws.recv(timeout=10)
            if isinstance(msg, bytes):
                continue
            d = json.loads(msg)
            if d["type"] == "effect.error":
                refused = d["error"]
            elif d["type"] == "scan.detections":
                detections += 1
            elif d["type"] == "job" and d["status"] in ("done", "error", "cancelled"):
                final = d
        stop.set()
        assert final["status"] == "done", final
        assert final["result"]["counts"]["ok"] > 200, final
        assert refused and "using the LEDs" in refused
        assert detections > 5
        assert (cfg.scan_dir / "round_01.npz").exists()

        url = f"http://127.0.0.1:{srv.port}/api/compare"
        cmp = json.load(urllib.request.urlopen(url))
        ok = [e for e, s in zip(cmp["errors_m"], cmp["status"]) if s == "ok"]
        assert len(cmp["positions"]) == 400 and np.median(ok) < 0.02
