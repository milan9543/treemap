"""The virtual WLED (``treemap sim wled``) and its flat layouts."""

from __future__ import annotations

import asyncio
import threading
import time

import numpy as np
import pytest
from scipy.spatial import cKDTree

from treemap.config import config_from_dict
from treemap.devices import probe, wled_led_count
from treemap.outputs.wled import Controller, WledOutput
from treemap.sim.flat import FlatSpec, generate_flat
from treemap.sim.tree import SpecError
from treemap.sim.virtual_wled import VirtualWled, new_layout


@pytest.mark.parametrize("pattern", ["rows", "spiral"])
def test_flat_layouts(pattern):
    f = generate_flat(FlatSpec.uniform(300, 2, pattern=pattern, quirks=False), seed=5)
    p = f.positions
    assert p.shape == (300, 3) and np.all(p[:, 2] == 0) and p[:, 1].min() >= 0.4
    steps = np.linalg.norm(np.diff(p, axis=0), axis=1)
    assert np.median(steps) == pytest.approx(f.strands[0].spacing, rel=0.1)
    assert steps.max() < 0.2  # no reversed strips: one unbroken path
    # LEDs that aren't neighbours along the strip stay apart, so a camera can tell them apart
    d, i = cKDTree(p).query(p, k=6)
    others = np.abs(i - np.arange(len(p))[:, None]) > 2
    assert d[others].min() > 0.05
    again = generate_flat(FlatSpec.uniform(300, 2, pattern=pattern, quirks=False), seed=5)
    assert np.array_equal(again.positions, p)
    with pytest.raises(SpecError):
        new_layout("flat", {"pattern": "zigzag"})


@pytest.fixture
def device(tmp_path):
    wled = VirtualWled(tmp_path / "layout.json", host="127.0.0.1", port=0, ddp_port=0)
    wled.use(new_layout("flat", {"strips": [{"leds": 120}], "seed": 1}))
    wled.open_ddp()
    loop = asyncio.new_event_loop()
    ready, stop = threading.Event(), loop.create_future()
    thread = threading.Thread(target=loop.run_until_complete,
                              args=(wled.serve(stop, on_ready=lambda _: ready.set()),), daemon=True)
    thread.start()
    assert ready.wait(5)
    yield wled
    loop.call_soon_threadsafe(stop.set_result, None)
    thread.join(5)


def test_serve_drives_it_like_real_wled(device):
    # The LED count comes from its /json/info, with the HTTP port in the host...
    host = f"127.0.0.1:{device.port}"
    assert wled_led_count(probe(host)) == 120
    # ...and frames go over DDP to its UDP port, as to a real controller.
    out = WledOutput(120, [Controller(host, 0, 120)], port=device.ddp_port)
    try:
        frame = np.zeros((120, 3), np.uint8)
        frame[7] = [255, 40, 0]
        out.show(frame)
        deadline = time.monotonic() + 3
        while device.last_frame is None and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        out.close()
    assert device.last_frame == frame.tobytes()
    assert device.status()["live"] and device.status()["source"] == "127.0.0.1"


def test_the_server_adds_it_by_address(device, tmp_path):
    """No controllers in the config: it's added by address, its LED count and that it's
    virtual are read from it, effects reach it, and the page can keep them to itself."""
    from tests.test_api import call
    from treemap.api import Api, HttpServer

    cfg = config_from_dict({})
    cfg.base_dir = tmp_path
    api = Api(cfg, open_leds=lambda r, c: WledOutput(
        c.led_count, [Controller(r.host, 0, c.led_count)], port=device.ddp_port))
    server = HttpServer(api.router, "127.0.0.1", 0, []).start()
    root = f"http://127.0.0.1:{server.port}/api/v2"
    try:
        assert call(root + "/devices")[2]["devices"] == []
        status, _, d = call(root + "/devices", {"host": f"http://127.0.0.1:{device.port}/"})
        assert status == 201, d
        assert (d["led_count"], d["virtual"], d["status"]["alive"]) == (120, True, True)
        assert d["name"] == "treemap virtual WLED" and d["gamma"] == 1.0
        assert call(root + "/devices", {"host": f"127.0.0.1:{device.port}"})[0] == 409

        base = f"{root}/devices/{d['id']}"
        assert call(base + "/play", {"effect": "solid", "params": {"color": "red"}})[0] == 200
        deadline = time.monotonic() + 5
        while device.last_frame is None or not (device.last_frame[0] > 100
                                                 and device.last_frame[1:3] == b"\0\0"):
            assert time.monotonic() < deadline, device.last_frame
            time.sleep(0.05)
        frame = call(base + "/frame")[2]
        assert frame["seq"] > 0 and frame["rgb"]

        assert call(base + "/send", {"on": False})[0] == 200  # the page only: LEDs dark
        time.sleep(0.3)
        assert not any(device.last_frame)
        assert call(base + "/frame")[2]["seq"] > frame["seq"]  # the page still gets them

        # A controller that's off: on the list, not answering, nothing to drive yet.
        status, _, off = call(root + "/devices", {"host": "127.0.0.1:9", "name": "Garden"})
        assert status == 201 and off["led_count"] is None and off["status"]["alive"] is False
        assert call(f"{root}/devices/{off['id']}/play", {"effect": "solid"})[0] == 409
        assert [x["name"] for x in call(root + "/devices")[2]["devices"]] == [
            "treemap virtual WLED", "Garden"]
        assert call(f"{root}/devices/{off['id']}", method="DELETE")[0] == 200
        assert len(Api(cfg, check_s=60).devices) == 1  # kept in data/devices.json
    finally:
        server.stop()
        api.close()
