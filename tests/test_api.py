"""``treemap serve``'s API: CORS, a device's LED commands and effects, favourites and
playlists, and a whole scan done the way the phone's page does it: frames POSTed in
batches, progress polled."""

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
from treemap.api.device import DeviceApi
from treemap.cameras.http import pack_batch
from treemap.config import config_from_dict
from treemap.outputs.base import LedOutput
from treemap.sim.tree import SimTree, generate_tree

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
    """A server with one device (whose controller is off) for a simulated tree's LEDs
    (``sim_tree(api)``): the device's API and the base of its endpoints.
    ``dev.output.frame`` is what its LEDs show."""
    servers = []

    def _serve(**cfg_overrides) -> tuple[DeviceApi, str]:
        cfg = config_from_dict({"server": {"origins": [PAGE]}, **cfg_overrides})
        cfg.base_dir = tmp_path
        tree = generate_tree(seed=3)
        tree.save(tmp_path / "sim_tree.json")
        api = Api(cfg, open_leds=lambda record, c: Recorder(record.led_count), check_s=60)
        server = HttpServer(api.router, "127.0.0.1", 0, cfg.server.origins).start()
        servers.append((server, api))
        root = f"http://127.0.0.1:{server.port}/api/v2"
        status, _, device = call(root + "/devices", {"host": "127.0.0.1:9", "name": "Tree",
                                                     "led_count": tree.led_count})
        assert status == 201, device
        return api.devices[device["id"]].api, f"{root}/devices/{device['id']}"

    yield _serve
    for server, api in servers:
        server.stop()
        api.close()


def sim_tree(api) -> SimTree:
    """The simulated tree the ``serve`` fixture's device has the LEDs of."""
    return SimTree.load(api.cfg.base_dir / "sim_tree.json")


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
    status, _, info = call(base.rsplit("/devices/", 1)[0] + "/info")
    assert status == 200 and info["api"] == 2
    status, _, device = call(base)
    assert status == 200 and device["led_count"] == 400 and device["name"] == "Tree"
    assert device["map"] is None and device["busy"] is None
    assert device["status"]["alive"] is False  # nothing answers on port 9

    status, headers, _ = call(base + "/leds", method="OPTIONS", headers={
        "Origin": PAGE, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Private-Network": "true"})
    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == PAGE
    assert headers["Access-Control-Allow-Private-Network"] == "true"
    assert call(base, headers={"Origin": PAGE})[1]["Access-Control-Allow-Origin"] == PAGE

    status, headers, body = call(base, headers={"Origin": "https://evil.example"})
    assert status == 403 and "server.origins" in body["error"]
    assert "Access-Control-Allow-Origin" not in headers
    assert call(base + "/leds", raw=b'{"mode": "off"}', ctype="text/plain")[0] == 415


def test_led_commands_and_an_effect(serve):
    api, base = serve()
    out = api.output
    assert call(base + "/leds", {"mode": "white", "level": 50})[0] == 200
    assert (out.frame == 50).all()
    call(base + "/leds", {"mode": "led", "index": 3, "color": "red"})
    assert out.frame[3].tolist() == [255, 0, 0] and out.frame.sum() == 255

    status, _, body = call(base + "/leds", {"mode": "chase", "speed": 500})
    assert status == 200 and body["seconds"] == 0.8
    assert call(base)[2]["busy"] == "leds"
    time.sleep(1.2)
    assert out.frame.sum() == 0 and call(base)[2]["busy"] is None

    for bad in ({"mode": "disco"}, {"mode": "led", "index": 400}, {"mode": "status"}):
        status, _, body = call(base + "/leds", bad)
        assert status == 400, (bad, body)

    assert call(base + "/play", {"effect": "rainbow"})[0] == 200
    time.sleep(0.6)
    info = call(base)[2]
    assert info["busy"] == "effect" and info["effect"] == "rainbow"
    assert info["timing"]["fps"] > 10 and info["timing"]["render_ms"]["median"] < 50
    assert 0 < info["timing"]["gap_ms"]["median"] <= info["timing"]["gap_ms"]["max"]
    assert out.frame.any()
    call(base + "/leds", {"mode": "off"})  # a test pattern replaces the effect
    assert call(base)[2]["busy"] is None and not out.frame.any()
    assert call(base + "/play", {"effect": "nope"})[0] == 404


def test_effects_favourites_and_playlists(serve):
    api, base = serve(engine={"crossfade": 0})
    root = base.rsplit("/devices/", 1)[0]
    effects = call(root + "/effects")[2]["effects"]
    rainbow = next(e for e in effects if e["name"] == "rainbow")
    assert not rainbow["needs_map"] and rainbow["params"]
    assert {e["group"] for e in effects} == {"3D", "Classic"}  # no test patterns

    # A favourite keeps every setting; changing them live shows it's changed from it.
    status, _, fav = call(root + "/favourites", {"name": "Fast", "effect": "rainbow",
                                                 "params": {"speed": 2}})
    assert status == 201 and fav["params"]["speed"] == 2 and len(fav["params"]) > 1
    assert call(root + "/favourites", {"name": "x", "effect": "rainbow",
                                       "params": {"nope": 1}})[0] == 400
    playing = call(base + "/play", {"favourite": fav["id"]})[2]
    assert playing["effect"] == "rainbow" and playing["favourite"] == fav["id"]
    assert playing["params"] == fav["params"]
    playing = call(base + "/play/params", {"params": {"speed": 1}})[2]
    assert playing["params"]["speed"] == 1 and playing["favourite"] == fav["id"]
    assert call(base + "/brightness", {"brightness": 0.5})[2]["brightness"] == 0.5
    status, _, fav = call(root + f"/favourites/{fav['id']}", {"name": "Slow",
                                                             "params": playing["params"]}, "PUT")
    assert status == 200 and fav["name"] == "Slow" and fav["params"]["speed"] == 1

    status, _, solid = call(root + "/favourites", {"name": "Red", "effect": "solid",
                                                   "params": {"color": "red"}})
    assert status == 201

    # A playlist moves on by itself; deleting a favourite takes it out of playlists.
    items = [{"favourite": fav["id"], "duration_s": 5}, {"favourite": solid["id"], "duration_s": 5}]
    status, _, pl = call(root + "/playlists", {"name": "Evening", "items": items})
    assert status == 201 and pl["crossfade_s"] == 3
    assert call(root + "/playlists", {"name": "Bad", "items": [{"favourite": "nope"}]})[0] == 400
    playing = call(base + "/play", {"playlist": pl["id"]})[2]
    assert playing["playlist"]["id"] == pl["id"] and playing["effect"] == "rainbow"
    playing = call(base + "/play/next", {})[2]
    assert playing["effect"] == "solid" and playing["favourite"] == solid["id"]
    assert playing["playlist"]["item"] == 1

    assert call(base + "/leds", {"mode": "white"})[0] == 200  # a test pattern ends it
    assert call(base + "/play")[2]["playlist"] is None
    assert call(root + f"/favourites/{solid['id']}", method="DELETE")[0] == 200
    assert call(root + "/playlists")[2]["playlists"][0]["items"] == items[:1]
    assert call(root + "/favourites/nope", method="DELETE")[0] == 404
    assert call(base + "/stop", {})[2]["effect"] is None and not api.output.frame.any()


def phone(base: str, api: Api, tree: SimTree, stop: threading.Event,
          clock: dict | None = None) -> None:
    """Plays the page: films the LEDs walking round the tree, uploads every 250 ms.
    ``clock["t"]`` is the latest frame's time."""
    t0 = time.monotonic()
    batch, sent = [], time.monotonic()
    while not stop.is_set():
        t = time.monotonic() - t0
        if clock is not None:
            clock["t"] = t
        eye, R = walk_pose(t, tree.height, lap_s=6.0)
        img, _ = render(tree.positions, api.output.frame, eye, R)
        batch.append(({"t": t, "fov_v": 55.0}, cv2.imencode(".jpg", img)[1].tobytes()))
        if time.monotonic() - sent >= 0.25:
            try:
                call(base + "/scan/frames", raw=pack_batch(batch), ctype="application/octet-stream")
            except OSError:
                if stop.is_set():
                    return  # the test is over and its server is shutting down
                raise
            batch, sent = [], time.monotonic()
        time.sleep(max(1 / 24 - (time.monotonic() - t0 - t), 0))


def test_a_scan_through_the_api(serve):
    api, base = serve(scan={"round_s": 7.0, "status_s": 0.5, "countdown_s": 0.5})
    tree = sim_tree(api)
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
    info = call(base)[2]
    assert info["map"]["fits"] and info["map"]["shape"] == "tree"
    assert call(base + "/scan/frames", raw=b"\x09\x00\x00\x00abc",
                ctype="application/octet-stream")[0] == 400

    # An LED in the wrong place: ignore its readings. The map is solved again, and
    # keeps facing the way it was set to.
    assert call(base + "/map/orientation", {"front_deg": 120})[0] == 200
    i = st["led_status"].index("o", 50)
    status, _, m = call(base + "/map/interpolate", {"index": i})
    assert status == 200, m
    assert m["ignored"] == [i] and m["led_status"][i] != "o"
    assert m["orientation"] == {"front_deg": 120.0}

    # A scan stopped before it made a map doesn't pass the old map off as its own.
    assert call(base + "/scan/start", {"rounds": 1})[0] == 202
    call(base + "/scan/stop", {})
    assert api.jobs.wait(10)
    st = call(base + "/scan/state")[2]
    assert st["status"] == "cancelled" and "led_status" not in st


def test_the_page_sets_the_phone_up(serve):
    """A scan that names its phone waits for the page to set the exposure (probing how
    many LEDs the frames show), then measures and keeps that phone's colours."""
    api, base = serve(scan={"countdown_s": 0.3})
    tree = sim_tree(api)
    stop = threading.Event()
    clock: dict[str, float] = {}
    threading.Thread(target=phone, args=(base, api, tree, stop, clock), daemon=True).start()
    try:
        assert call(base + "/scan/camera-ready", {})[0] == 409  # no scan is waiting
        assert call(base + "/scan/start", {"camera": "Pixel 9 camera2 0, facing back"})[0] == 202
        deadline = time.monotonic() + 20
        while call(base + "/scan/state")[2]["phase"] != "exposure":
            assert time.monotonic() < deadline
            time.sleep(0.1)
        status, _, probe = call(base + "/scan/exposure-probe", {"since": clock["t"], "frames": 4})
        assert status == 200 and probe["frames"] == 4 and probe["leds"] > 100, probe
        assert call(base + "/scan/camera-ready", {"message": "exposure 2 ms",
                                                  "settings": {"exposureTime": 20}})[0] == 200
        while (st := call(base + "/scan/state")[2])["colours"] is None:
            assert time.monotonic() < deadline and st["status"] == "running", st
            time.sleep(0.2)
    finally:
        call(base + "/scan/stop", {})
        stop.set()
    assert st["colours"]["ok"], st["colours"]
    saved = json.loads(api.cfg.colours_path_for("Pixel 9 camera2 0, facing back").read_text())
    assert saved["camera"] == "Pixel 9 camera2 0, facing back"
    assert saved["camera_settings"] == {"exposureTime": 20}
    assert call(base + "/scan/exposure-probe", {"since": "now"})[0] == 400
