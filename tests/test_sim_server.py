import json
import os
import time
import urllib.error
import urllib.request

import numpy as np
import pytest
from websockets.sync.client import connect

from treemap.outputs.sim import SimOutput
from treemap.sim.server import ServerThread, SimServer
from treemap.sim.tree import SimTree, TreeSpec, generate_tree

SMALL = TreeSpec.uniform(10, 1)


@pytest.fixture
def server(tmp_path):
    tree_path = tmp_path / "sim_tree.json"
    generate_tree(SMALL, seed=3).save(tree_path)
    srv = SimServer(
        tree_path=tree_path,
        map_path=tmp_path / "tree_map.json",
        port=0,
        poll_s=0.05,
        led_count=10,
        defaults=TreeSpec.uniform(10, 2, height=1.5),
    )
    with ServerThread(srv):
        yield srv


def get(srv, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}{path}", timeout=5) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def recv_until(ws, predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        msg = ws.recv(timeout=end - time.monotonic())
        if predicate(msg):
            return msg
    raise TimeoutError


def test_serves_viewer_page(server):
    status, ctype, body = get(server, "/")
    assert status == 200 and ctype.startswith("text/html")
    assert b"three" in body and b"/ws/viewer" in body


def test_serves_tree_and_404s(server):
    status, ctype, body = get(server, "/api/tree")
    assert status == 200 and ctype == "application/json"
    assert json.loads(body)["led_count"] == 10
    for path in ("/api/map", "/nope"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(server, path)
        assert e.value.code == 404


def test_frames_are_relayed_to_viewers(server):
    with connect(f"ws://127.0.0.1:{server.port}/ws/viewer") as viewer:
        assert json.loads(viewer.recv(timeout=5))["type"] == "status"
        out = SimOutput(10, port=server.port)
        try:
            frame = np.arange(30, dtype=np.uint8).reshape(10, 3)
            out.show(frame)
            assert out.connected
            got = recv_until(viewer, lambda m: isinstance(m, bytes))
            assert got == frame.tobytes()
        finally:
            out.close()


def test_late_viewer_gets_last_frame(server):
    with SimOutput(10, port=server.port) as out:
        out.fill((1, 2, 3))
        deadline = time.monotonic() + 5
        while server.last_frame is None and time.monotonic() < deadline:
            time.sleep(0.01)
    with connect(f"ws://127.0.0.1:{server.port}/ws/viewer") as viewer:
        got = recv_until(viewer, lambda m: isinstance(m, bytes))
        assert got == bytes([1, 2, 3] * 10)


def test_viewers_told_to_reload_when_tree_changes(server):
    with connect(f"ws://127.0.0.1:{server.port}/ws/viewer") as viewer:
        time.sleep(0.15)  # let the watcher record the initial mtime
        generate_tree(SMALL, seed=4).save(server.tree_path)
        st = server.tree_path.stat()
        os.utime(server.tree_path, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        msg = recv_until(viewer, lambda m: isinstance(m, str) and "reload" in m)
        assert json.loads(msg) == {"type": "reload", "what": "tree"}


def test_config_endpoint(server):
    status, ctype, body = get(server, "/api/config")
    data = json.loads(body)
    assert status == 200 and ctype == "application/json"
    assert data["led_count"] == 10
    assert data["defaults"]["height"] == 1.5
    assert [s["leds"] for s in data["defaults"]["strips"]] == [5, 5]
    assert data["limits"]["strips"] == [1, 8]


def generate(ws, spec, request_id=1):
    ws.send(json.dumps({"type": "generate", "id": request_id, "spec": spec}))
    return json.loads(
        recv_until(ws, lambda m: isinstance(m, str) and '"generated"' in m, timeout=20)
    )


def test_generate_from_viewer_saves_tree_and_reloads(server):
    with connect(f"ws://127.0.0.1:{server.port}/ws/viewer") as viewer:
        spec = {
            "strips": [{"leds": 30, "length": 2.4, "start": "top"}, {"leds": 20, "length": None}],
            "height": 1.4, "radius": None, "layout": "interleaved", "quirks": False, "seed": 11,
        }
        reply = generate(viewer, spec, request_id=7)
        warnings = reply.pop("warnings")
        assert reply == {"type": "generated", "id": 7, "ok": True, "seed": 11, "led_count": 50}
        assert len(warnings) == 2 and "too short" in warnings[0]  # 2.4 m and 1.3 m strips
        tree = SimTree.load(server.tree_path)
        assert [s.count for s in tree.strands] == [30, 20]
        assert tree.strands[0].index_from_top and tree.height == 1.4
        recv_until(viewer, lambda m: isinstance(m, str) and "reload" in m)


def test_generate_reports_bad_spec(server):
    before = server.tree_path.read_bytes()
    with connect(f"ws://127.0.0.1:{server.port}/ws/viewer") as viewer:
        reply = generate(viewer, {"strips": [{"leds": 100, "length": 0.2}]})
        assert reply["ok"] is False and "cm between LEDs" in reply["error"]
        reply = generate(viewer, "nonsense")
        assert reply["ok"] is False
    assert server.tree_path.read_bytes() == before  # unchanged


@pytest.fixture
def fx_server(tmp_path):
    """A server whose effects engine streams back into its own viewers (like `sim view`)."""
    from treemap.effects import EffectContext
    from treemap.engine import Engine

    srv = SimServer(
        tree_path=tmp_path / "t.json", map_path=tmp_path / "m.json", port=0, led_count=10,
        make_engine=lambda s: Engine(
            lambda: SimOutput(10, port=s.port), EffectContext(n=10), fps=50, crossfade_s=0
        ),
    )
    with ServerThread(srv):
        yield srv


def engine_state(ws, pred=lambda st: True):
    msg = recv_until(ws, lambda m: isinstance(m, str) and '"engine"' in m and pred(json.loads(m)))
    return json.loads(msg)


def test_effects_endpoint(fx_server):
    data = json.loads(get(fx_server, "/api/effects")[2])
    assert data["available"] is True and data["output"] == "sim"
    names = [e["name"] for e in data["effects"]]
    assert "rainbow" in names and "led" in names
    led = next(e for e in data["effects"] if e["name"] == "led")
    assert led["params"][0]["max"] == 9


def test_viewer_runs_tunes_and_stops_effects(fx_server):
    with connect(f"ws://127.0.0.1:{fx_server.port}/ws/viewer") as viewer:
        assert engine_state(viewer)["running"] is None  # sent on connect
        viewer.send(json.dumps({"type": "effect.run", "effect": "solid",
                                "params": {"color": "#ff0000"}}))
        st = engine_state(viewer, lambda s: s["running"] == "solid")
        assert st["params"] == {"color": "#ff0000"} and st["output"] == "sim"
        # the engine's frames come back through the sim output to this viewer
        frame = recv_until(viewer, lambda m: isinstance(m, bytes) and m[:3] == bytes([255, 0, 0]))
        assert frame == bytes([255, 0, 0] * 10)

        viewer.send(json.dumps({"type": "effect.params", "params": {"color": "#0000ff"}}))
        viewer.send(json.dumps({"type": "effect.brightness", "value": 0.5}))
        engine_state(viewer, lambda s: s["brightness"] == 0.5)
        recv_until(viewer, lambda m: isinstance(m, bytes) and m == bytes([0, 0, 128] * 10))

        viewer.send(json.dumps({"type": "effect.stop"}))
        seen = set()  # the off frame and the stopped state, in either order

        def done(m):
            if isinstance(m, bytes) and not any(m):
                seen.add("off")
            elif isinstance(m, str) and json.loads(m).get("type") == "engine" \
                    and json.loads(m)["running"] is None:
                seen.add("stopped")
            return seen == {"off", "stopped"}

        recv_until(viewer, done)


@pytest.mark.parametrize(
    "msg, match",
    [
        ({"type": "effect.run", "effect": "disco"}, "unknown effect"),
        ({"type": "effect.run", "effect": "solid", "params": {"colour": 1}}, "no parameter"),
        ({"type": "effect.run", "effect": "solid", "params": [1]}, "params must be an object"),
        ({"type": "effect.params", "params": {"color": "red"}}, "no effect is running"),
        ({"type": "effect.brightness", "value": "high"}, "brightness"),
        ({"type": "effect.brightness", "value": 3}, "brightness must be 0-1"),
        ({"type": "effect.dance"}, "unknown command"),
    ],
)
def test_bad_effect_commands_are_reported(fx_server, msg, match):
    with connect(f"ws://127.0.0.1:{fx_server.port}/ws/viewer") as viewer:
        viewer.send(json.dumps(msg))
        err = recv_until(viewer, lambda m: isinstance(m, str) and "effect.error" in m)
        assert match in json.loads(err)["error"]


def test_effects_unavailable_without_engine(server):
    assert json.loads(get(server, "/api/effects")[2])["available"] is False
    with connect(f"ws://127.0.0.1:{server.port}/ws/viewer") as viewer:
        viewer.send(json.dumps({"type": "effect.run", "effect": "solid"}))
        err = recv_until(viewer, lambda m: isinstance(m, str) and "effect.error" in m)
        assert "not available" in err


def test_sim_output_without_server_keeps_frames():
    out = SimOutput(4, port=1)  # nothing listens on port 1
    out.fill((9, 9, 9))
    assert not out.connected
    assert out.last_frame.tolist() == [[9, 9, 9]] * 4
    out.off()  # retry is throttled: no second slow connect attempt, no error
    assert not out.last_frame.any()
    out.close()


def test_viewer_is_told_who_is_sending(server):
    with connect(f"ws://127.0.0.1:{server.port}/ws/viewer") as viewer:
        a = SimOutput(10, port=server.port, source="viewer: effects")
        b = SimOutput(10, port=server.port)  # defaults to this program's command line
        a.off()
        b.off()
        msg = recv_until(viewer, lambda m: isinstance(m, str) and '"producers": 2' in m)
        sources = json.loads(msg)["sources"]
        assert "viewer: effects" in sources
        assert any(s.startswith("treemap") and "pid" in s for s in sources)
        b.close()
        recv_until(viewer, lambda m: isinstance(m, str) and '"producers": 1' in m)
        a.close()
