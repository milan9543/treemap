"""``WledOutput``: frames to WLED controllers over DDP (UDP port 4048).

Each controller owns a slice of the global LED index (``controllers`` in the config)
and gets it as its own LEDs 0, 1, ..., reversed if ``reverse`` is set.

WLED shows realtime data while it keeps arriving and drops back to its own effect when
it stops for a while (2.5 s by default). Callers don't always send that often (a scan
shows its status colours for several seconds), so the last frame is re-sent every
``keepalive_s`` while nothing new is shown.

A DDP packet is a 10-byte header followed by RGB bytes:

====  ==================================================================
0     flags: version 1 (0x40), plus push (0x01) on a frame's last packet
1     sequence number 1-15 (0 means unused)
2     data type 0x0B: RGB, 8 bits per channel
3     destination 1: the default output
4-7   where this packet's data starts in the frame, in bytes, big-endian
8-9   data length in bytes, big-endian
====  ==================================================================
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from typing import Any

import numpy as np

from treemap.config import Controller
from treemap.outputs.base import LedOutput, OutputError

log = logging.getLogger(__name__)

DDP_PORT = 4048
MAX_PIXELS = 480  # per packet: 1440 bytes of RGB stays under a 1500-byte Ethernet frame
FLAG_VERSION_1 = 0x40
FLAG_PUSH = 0x01
TYPE_RGB8 = 0x0B
DEST_DEFAULT = 1


def ddp_packets(rgb: bytes, seq: int) -> list[bytes]:
    """One frame of RGB bytes as DDP packets; the last one tells WLED to show it."""
    step = MAX_PIXELS * 3
    chunks = [rgb[i:i + step] for i in range(0, len(rgb), step)] or [b""]
    packets = []
    for k, chunk in enumerate(chunks):
        flags = FLAG_VERSION_1 | (FLAG_PUSH if k == len(chunks) - 1 else 0)
        header = struct.pack(">BBBBIH", flags, seq, TYPE_RGB8, DEST_DEFAULT, k * step, len(chunk))
        packets.append(header + chunk)
    return packets


def resolve(host: str, port: int) -> tuple[str, int]:
    """``host`` (a name, ``.local`` included, or an IP address) as an IPv4 address."""
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)
    except socket.gaierror as e:
        raise OutputError(
            f"can't find the WLED controller {host!r} ({e.strerror}); check its host in "
            "`controllers` in the config. Its IP address works where a .local name doesn't."
        ) from None
    return infos[0][4][:2]


class WledOutput(LedOutput):
    def __init__(self, led_count: int, controllers: list[Controller], port: int = DDP_PORT,
                 keepalive_s: float = 1.0) -> None:
        super().__init__(led_count)
        for i, c in enumerate(controllers):
            if c.start + c.count > led_count:
                raise ValueError(f"controllers[{i}] drives LEDs beyond the {led_count} there are")
        self._targets = [(c, resolve(c.host, port)) for c in controllers]
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._lock = threading.Lock()
        self._seq = 0
        self._last: np.ndarray | None = None
        self._sent_at = 0.0
        self._failing: set[str] = set()  # hosts we've warned about, until a send works
        self.keepalive_s = keepalive_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._keepalive, name="wled-keepalive",
                                        daemon=True)
        self._thread.start()

    def _show(self, colors: np.ndarray) -> None:
        with self._lock:
            self._send(colors)
            self._last = colors.copy()

    def _send(self, colors: np.ndarray) -> None:
        self._seq = self._seq % 15 + 1
        for c, addr in self._targets:
            part = colors[c.start:c.start + c.count]
            if c.reverse:
                part = part[::-1]
            try:
                for packet in ddp_packets(part.tobytes(), self._seq):
                    self._sock.sendto(packet, addr)
            except OSError as e:  # e.g. the network went away; keep trying
                if c.host not in self._failing:
                    log.warning("can't send to the WLED controller %s (%s)", c.host, e)
                    self._failing.add(c.host)
            else:
                self._failing.discard(c.host)
        self._sent_at = time.monotonic()

    def _keepalive(self) -> None:
        while not self._stop.wait(self.keepalive_s / 4):
            with self._lock:
                if (self._last is not None
                        and time.monotonic() - self._sent_at >= self.keepalive_s):
                    self._send(self._last)

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._sock.close()


# -- checking a controller over WLED's JSON API ------------------------------------------


def fetch_state(host: str, timeout: float = 3.0) -> dict[str, Any]:
    """WLED's ``/json`` (``state`` and ``info``). Raises ``OutputError`` if unreachable."""
    import requests

    try:
        r = requests.get(f"http://{host}/json", timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except requests.ConnectionError:
        raise OutputError(f"can't connect to http://{host}/: is the controller on and on "
                          "this network?") from None
    except requests.Timeout:
        raise OutputError(f"http://{host}/ didn't answer within {timeout:g} s") from None
    except (requests.RequestException, ValueError) as e:
        raise OutputError(f"no WLED answering at http://{host}/ ({e})") from None
    if not isinstance(data, dict) or "info" not in data:
        raise OutputError(f"http://{host}/json isn't WLED's JSON API")
    return data


def check_problems(c: Controller, data: dict[str, Any], index: int = 0) -> list[str]:
    """What in WLED's settings doesn't fit controller ``c`` of the config."""
    problems = []
    info, state = data.get("info", {}), data.get("state", {})
    count = info.get("leds", {}).get("count")
    if isinstance(count, int) and count != c.count:
        if count < c.count:
            problems.append(
                f"WLED is set up for {count} LEDs but controllers[{index}].count is {c.count}: "
                f"LEDs beyond {count} stay dark. Set the LED count in WLED's LED Preferences."
            )
        else:
            problems.append(
                f"WLED is set up for {count} LEDs but controllers[{index}].count is {c.count}: "
                f"its LEDs beyond {c.count} won't get treemap's colours."
            )
    bri = state.get("bri")
    if isinstance(bri, int) and bri < 255:
        problems.append(
            f"WLED's brightness is {bri}/255 and it dims treemap's colours too. Set it to "
            "full, or tick \"Force max brightness\" in WLED's Sync Interfaces settings "
            "(treemap has its own brightness, engine.brightness)."
        )
    return problems
