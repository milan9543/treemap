"""``treemap serve``'s API: CORS, LED commands and effects, and a whole scan done the way
the phone's page does it: frames POSTed in batches, progress polled."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import cv2
import numpy as np
import pytest

from tests.walk_render import render, walk_pose
from treemap.api import Api, HttpServer
from treemap.cameras.http import pack_batch
from treemap.config import config_from_dict
from treemap.outputs.base import LedOutput
from treemap.sim.tree import SimTree
from treemap.workflow import ensure_sim_tree

PAGE = "https://page.example"


class Recorder(LedOutput):
    """Keeps the latest frame, as the real LEDs would show it."""

    def __init__(self, n: int) -> None:
        super().__init__(n)
        self.last = np.zeros((n, 3), np.uint8)

    def _show(self, colors: np.ndarray) -> None:
        self.last = colors.copy()


@pytest.fixture
def serve(tmp_path):
    servers = []

    def _serve(**cfg_overrides):
        cfg = config_from_dict({"server": {"origins": [PAGE]}, "sim": {"seed": 3},
                                **cfg_overrides})
        cfg.base_dir = tmp_path
        ensure_sim_tree(cfg)
        api = Api(cfg, Recorder(cfg.led_count))
        server = HttpServer(api.router, "127.0.0.1", 0, cfg.server.origins).start()
        servers.append((server, api))
        return api, f"http://127.0.0.1:{server.port}/api/v1"

    yield _serve
    for server, api in servers:
        server.stop()
        api.close()


def call(url, body=None, method=None, headers=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": ctype} if data is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers={**h, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read()
            return r.status, dict(r.headers), json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read() or b"null")


def test_info_and_cors(serve):
    api, base = serve()
    status, _, info = call(base + "/info")
    assert status == 200 and info["api"] == 1 and info["led_count"] == 400
    assert info["map"] is None and info["busy"] is None

    status, headers, _ = call(base + "/leds", method="OPTIONS", headers={
        "Origin": PAGE, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Private-Network": "true"})
    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == PAGE
    assert headers["Access-Control-Allow-Private-Network"] == "true"
    assert call(base + "/info", headers={"Origin": PAGE})[1]["Access-Control-Allow-Origin"] == PAGE

    status, headers, body = call(base + "/info", headers={"Origin": "https://evil.example"})
    assert status == 403 and "server.origins" in body["error"]
    assert "Access-Control-Allow-Origin" not in headers
    assert call(base + "/leds", raw=b'{"mode": "off"}', ctype="text/plain")[0] == 415


def test_led_commands_and_an_effect(serve):
    api, base = serve()
    out = api.output
    assert call(base + "/leds", {"mode": "white", "level": 50})[0] == 200
    assert (out.last == 50).all()
    call(base + "/leds", {"mode": "led", "index": 3, "color": "red"})
    assert out.last[3].tolist() == [255, 0, 0] and out.last.sum() == 255

    status, _, body = call(base + "/leds", {"mode": "chase", "speed": 500})
    assert status == 200 and body["seconds"] == 0.8
    assert call(base + "/info")[2]["busy"] == "leds"
    time.sleep(1.2)
    assert out.last.sum() == 0 and call(base + "/info")[2]["busy"] is None

    for bad in ({"mode": "disco"}, {"mode": "led", "index": 400}, {"mode": "status"}):
        status, _, body = call(base + "/leds", bad)
        assert status == 400, (bad, body)

    assert call(base + "/play", {"effect": "rainbow"})[0] == 200
    time.sleep(0.6)
    info = call(base + "/info")[2]
    assert info["busy"] == "effect" and info["effect"] == "rainbow"
    assert info["timing"]["fps"] > 10 and info["timing"]["render_ms"]["median"] < 50
    assert out.last.any()
    call(base + "/leds", {"mode": "off"})  # a test pattern replaces the effect
    assert call(base + "/info")[2]["busy"] is None and not out.last.any()
    assert call(base + "/play", {"effect": "nope"})[0] == 404


def phone(base: str, api: Api, tree: SimTree, stop: threading.Event) -> None:
    """Plays the page: films the LEDs walking round the tree, uploads every 250 ms."""
    t0 = time.monotonic()
    batch, sent = [], time.monotonic()
    while not stop.is_set():
        t = time.monotonic() - t0
        eye, R = walk_pose(t, tree.height, lap_s=6.0)
        img, _ = render(tree.positions, api.output.last, eye, R)
        batch.append(({"t": t, "fov_v": 55.0}, cv2.imencode(".jpg", img)[1].tobytes()))
        if time.monotonic() - sent >= 0.25:
            call(base + "/scan/frames", raw=pack_batch(batch), ctype="application/octet-stream")
            batch, sent = [], time.monotonic()
        time.sleep(max(1 / 24 - (time.monotonic() - t0 - t), 0))


def test_a_scan_through_the_api(serve):
    api, base = serve(scan={"round_s": 7.0, "status_s": 0.5, "countdown_s": 0.5})
    tree = SimTree.load(api.cfg.sim_tree_path)
    stop = threading.Event()
    threading.Thread(target=phone, args=(base, api, tree, stop), daemon=True).start()
    try:
        status, _, body = call(base + "/scan/start", {"rounds": 1})
        assert status == 202, body
        assert call(base + "/scan/start", {})[0] == 409  # one at a time
        assert call(base + "/leds", {"mode": "off"})[0] == 409  # the scan has the LEDs
        phases = set()
        deadline = time.monotonic() + 60
        while (st := call(base + "/scan/state")[2])["status"] == "running":
            phases.add(st["phase"])
            assert time.monotonic() < deadline, st
            time.sleep(0.3)
    finally:
        stop.set()
    assert st["status"] == "done", st
    assert {"countdown", "flashing"} <= phases
    assert st["counts"]["ok"] > 200, st
    assert len(st["led_status"]) == 400 and st["led_status"].count("o") == st["counts"]["ok"]
    assert st["frames_received"] > 100
    info = call(base + "/info")[2]
    assert info["map"]["fits"] and info["map"]["shape"] == "tree"
    assert call(base + "/scan/frames", raw=b"\x09\x00\x00\x00abc",
                ctype="application/octet-stream")[0] == 400
