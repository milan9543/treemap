"""The virtual WLED (``treemap sim wled``) and its flat layouts."""

from __future__ import annotations

import asyncio
import threading
import time

import numpy as np
import pytest
from scipy.spatial import cKDTree

from treemap.config import config_from_dict
from treemap.outputs.wled import WledOutput
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
    cfg = config_from_dict({"output": "wled", "controllers": [{"host": f"127.0.0.1:{device.port}"}]})
    layout = cfg.controller_layout()
    assert [(c.start, c.count) for c in layout] == [(0, 120)]
    # ...and frames go over DDP to its UDP port, as to a real controller.
    out = WledOutput(120, layout, port=device.ddp_port)
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
