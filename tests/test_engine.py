import threading
import time

import numpy as np
import pytest

from treemap.effects import EffectContext, ParamError
from treemap.engine import Engine

from .test_interfaces import RecordingOutput

N = 8


class ThreadSafeOutput(RecordingOutput):
    def __init__(self, n):
        super().__init__(n)
        self.lock = threading.Lock()

    def _show(self, colors):
        with self.lock:
            super()._show(colors)

    def last(self):
        with self.lock:
            return self.frames[-1].copy() if self.frames else None


def make(fps=200, crossfade=0.0, **kw):
    outputs = []

    def factory():
        out = ThreadSafeOutput(N)
        outputs.append(out)
        return out

    changes = []
    engine = Engine(
        factory, EffectContext(n=N), fps=fps, crossfade_s=crossfade,
        on_change=lambda: changes.append(engine.state()), **kw,
    )
    return engine, outputs, changes


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def test_runs_effect_and_stop_turns_off():
    engine, outputs, changes = make()
    engine.start("solid", {"color": "red"})
    wait_for(lambda: outputs and outputs[0].last() is not None)
    assert (outputs[0].last() == (255, 0, 0)).all()
    assert engine.state()["running"] == "solid"
    engine.stop()
    assert not engine.running
    assert not outputs[0].frames[-1].any()  # turned off
    assert outputs[0].closed
    assert changes[0]["running"] == "solid" and changes[-1]["running"] is None


def test_frame_rate_is_roughly_fixed():
    engine, outputs, _ = make(fps=50)
    engine.start("rainbow")
    time.sleep(0.5)
    engine.stop()
    assert 18 <= engine.frames <= 30


def test_brightness_scales_frames():
    engine, outputs, _ = make(brightness=0.5)
    engine.start("solid", {"color": "white"})
    wait_for(lambda: outputs and outputs[0].last() is not None)
    assert (outputs[0].last() == 128).all()
    engine.set_brightness(0.25)
    wait_for(lambda: (outputs[0].last() == 64).all())
    with pytest.raises(ValueError):
        engine.set_brightness(2)
    engine.stop()


def test_gamma_darkens_mid_levels_only():
    engine, _, _ = make(gamma=2.2)
    engine.start("solid", {"color": [255, 128, 0]})
    frame = engine.render_frame(time.perf_counter())
    assert tuple(frame[0]) == (255, 56, 0)  # 255 * (128/255)^2.2 ≈ 56
    engine.stop()


def test_live_params_and_validation():
    engine, outputs, changes = make()
    engine.start("solid", {"color": "red"})
    engine.set_params({"color": "blue"})
    wait_for(lambda: outputs and outputs[0].last() is not None
             and (outputs[0].last() == (0, 0, 255)).all())
    assert changes[-1]["params"] == {"color": "#0000ff"}
    with pytest.raises(ParamError):
        engine.set_params({"color": "plaid"})
    engine.stop()
    with pytest.raises(LookupError):
        engine.set_params({"color": "red"})


def test_switching_crossfades_on_one_output():
    engine, outputs, _ = make(crossfade=0.3)
    engine.start("solid", {"color": "red"})
    wait_for(lambda: outputs and outputs[0].last() is not None)
    engine.start("solid", {"color": "blue"})
    frame = engine.render_frame(time.perf_counter() + 0.15)  # mid-fade: both colours present
    assert frame[0, 0] > 0 and frame[0, 2] > 0
    wait_for(lambda: (outputs[0].last() == (0, 0, 255)).all())
    assert len(outputs) == 1  # same output, no reconnect
    engine.stop()


def test_bad_start_requests_raise_and_dont_start():
    engine, outputs, _ = make()
    with pytest.raises(KeyError):
        engine.start("disco")
    with pytest.raises(ParamError):
        engine.start("solid", {"colour": "red"})
    assert not engine.running and outputs == []


def test_effect_crash_stops_engine_and_reports():
    engine, outputs, changes = make()
    effect = engine.start("solid")
    effect.render = lambda t: 1 / 0
    assert engine.wait(3)
    assert "solid failed" in engine.error and "division by zero" in engine.error
    assert changes[-1]["running"] is None and changes[-1]["error"] == engine.error
    assert not outputs[0].frames or not outputs[0].frames[-1].any()
    engine.start("solid")  # recovers
    wait_for(lambda: len(outputs) == 2 and outputs[1].last() is not None)
    assert engine.error is None
    engine.stop()


def test_output_failure_is_reported():
    def factory():
        raise NotImplementedError("no WLED yet")

    engine = Engine(factory, EffectContext(n=N))
    engine.start("solid")
    assert engine.wait(3)
    assert engine.error == "no WLED yet"


def test_restart_after_stop():
    engine, outputs, _ = make()
    for color in ("red", "green"):
        engine.start("solid", {"color": color})
        wait_for(lambda: outputs[-1].last() is not None and outputs[-1].last().any())
        engine.stop()
    assert len(outputs) == 2
    assert np.array_equal(outputs[1].frames[0][0], [0, 255, 0])
