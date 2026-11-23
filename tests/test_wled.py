import socket
import struct

import numpy as np
import pytest

from treemap.devices import wled_problems
from treemap.outputs import OutputError
from treemap.outputs.wled import Controller, WledOutput, ddp_packets


def header(packet: bytes) -> tuple[int, int, int, int, int, int]:
    return struct.unpack(">BBBBIH", packet[:10])


def test_ddp_splits_a_frame_into_packets_and_pushes_on_the_last():
    rgb = bytes(range(256)) * 6  # 512 LEDs
    packets = ddp_packets(rgb[:512 * 3], seq=7)
    assert [header(p) for p in packets] == [
        (0x40, 7, 0x0B, 1, 0, 1440),
        (0x41, 7, 0x0B, 1, 1440, 96),
    ]
    assert b"".join(p[10:] for p in packets) == rgb[:512 * 3]


@pytest.fixture
def receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2)
    yield sock
    sock.close()


def test_frames_are_split_across_controllers_and_kept_alive(receiver):
    port = receiver.getsockname()[1]
    controllers = [Controller("127.0.0.1", 0, 3), Controller("127.0.0.1", 3, 2, reverse=True)]
    out = WledOutput(5, controllers, port=port, keepalive_s=0.1)
    try:
        frame = np.arange(15, dtype=np.uint8).reshape(5, 3)
        out.show(frame)
        first, second = receiver.recv(2000), receiver.recv(2000)
        assert first[10:] == frame[:3].tobytes()
        assert second[10:] == frame[[4, 3]].tobytes()  # reversed slice, from offset 0
        assert header(second)[4] == 0
        # nothing new shown: the last frame is re-sent so WLED stays in realtime mode
        assert receiver.recv(2000)[10:] == frame[:3].tobytes()
    finally:
        out.close()


def test_unknown_host_is_a_clear_error():
    with pytest.raises(OutputError, match="can't find the WLED controller 'no-such-wled.invalid'"):
        WledOutput(10, [Controller("no-such-wled.invalid", 0, 10)])


def test_wled_settings_that_get_in_the_way():
    fine = ({"bri": 255}, {"wifi": {"sleep": False}, "if": {"live": {"en": True}}})
    assert wled_problems(*fine) == []
    problems = wled_problems({"bri": 128}, {"wifi": {"sleep": True},
                                            "if": {"live": {"en": False}}})
    assert len(problems) == 3
    assert "Receive UDP realtime" in problems[0] and "128/255" in problems[1]
    assert "Disable WiFi sleep" in problems[2]
    # dimmed, but WLED shows realtime colours at full anyway
    assert wled_problems({"bri": 128}, {"if": {"live": {"maxbri": True}}}) == []
