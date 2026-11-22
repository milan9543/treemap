"""The devices ``treemap serve`` drives: WLED controllers added on its page, by address.

Each device is its own set of LEDs, with its own map and scans in ``data/devices/<id>/``.
The list is kept in ``data/devices.json``; the first time the server runs it's empty.
A device's LED count is read from its WLED when it's added (or the first time it answers)
and kept, so a scanned device can still be shown, and effects previewed on it, while its
controller is off.

The virtual WLED of ``treemap sim wled`` is added the same way, by its address; it
answers WLED's JSON API as a ``"treemap virtual"`` product, so it's shown as virtual.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from treemap.outputs.base import LedOutput, OutputError

log = logging.getLogger(__name__)

MAX_DEVICES = 50
MAX_LEDS = 5000
PROBE_TIMEOUT_S = 2.5
VIRTUAL_PRODUCT = "treemap virtual"


class DeviceError(ValueError):
    """A device that can't be added or changed as asked."""


@dataclass
class DeviceRecord:
    id: str
    name: str
    host: str  # a name or IP address, with :port for a WLED not on port 80
    led_count: int | None = None  # from WLED; None until it has answered once
    virtual: bool = False  # the virtual WLED of `treemap sim wled`


def normalise_host(text: Any) -> str:
    """``http://192.168.1.20/`` → ``192.168.1.20``; keeps a port. Raises DeviceError."""
    if not isinstance(text, str):
        raise DeviceError("host must be the controller's address")
    host = re.sub(r"^https?://", "", text.strip(), flags=re.I).split("/")[0]
    if not re.fullmatch(r"[A-Za-z0-9.-]+(:\d{1,5})?|\[[0-9a-fA-F:]+\](:\d{1,5})?", host):
        raise DeviceError(f"{text!r} isn't an address like 192.168.1.20 or wled.local")
    return host


def probe(host: str, timeout: float = PROBE_TIMEOUT_S) -> dict[str, Any]:
    """WLED's ``/json/info`` from ``host``. Raises OSError (and ValueError on a reply
    that isn't WLED's)."""
    with urllib.request.urlopen(f"http://{host}/json/info", timeout=timeout) as r:
        info = json.loads(r.read())
    if not isinstance(info, dict) or not isinstance(info.get("leds"), dict):
        raise ValueError(f"{host} answered, but not as WLED does")
    return info


def wled_led_count(info: dict[str, Any]) -> int:
    count = info["leds"].get("count")
    if not isinstance(count, int) or not 1 <= count <= MAX_LEDS:
        raise ValueError(f"WLED reports {count!r} LEDs; set the LED count in its LED Preferences")
    return count


class DeviceStore:
    """``data/devices.json``: the devices, in the order they were added."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> list[DeviceRecord]:
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return []
        fields = set(DeviceRecord.__dataclass_fields__)
        return [DeviceRecord(**{k: v for k, v in d.items() if k in fields})
                for d in data.get("devices", [])]

    def save(self, devices: list[DeviceRecord]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"version": 1, "devices": [asdict(d) for d in devices]},
                                      indent=1) + "\n")
            os.replace(tmp, self.path)

    @staticmethod
    def new_id(taken: set[str]) -> str:
        while (new := secrets.token_hex(3)) in taken:
            pass
        return new


class DeviceOutput(LedOutput):
    """A device's LEDs: every frame is kept (for the server's page to show), and sent to
    the controller unless :attr:`send` is off (to preview an effect on the page only).

    The controller's output is opened when first needed, and again a while after it
    fails (a ``.local`` name that doesn't resolve while the controller is off), so the
    server runs, and effects play on the page, without the controller."""

    RETRY_S = 5.0

    def __init__(self, led_count: int, open_leds: Callable[[], LedOutput]) -> None:
        super().__init__(led_count)
        self._open = open_leds
        self._leds: LedOutput | None = None
        self._failed_at = -math.inf
        self._opening = False
        self._closed = False
        self._lock = threading.Lock()
        self.send = True
        self.frame = np.zeros((led_count, 3), np.uint8)
        self.seq = 0  # frames shown so far
        self.error: str | None = None  # why the controller's output couldn't be opened

    def _leds_now(self) -> LedOutput | None:
        """The controller's output, if it's open (under the lock). Opening it (a name
        lookup can take seconds while the controller is off) happens on a thread of its
        own, so frames meanwhile only go to the page."""
        if (self._leds is None and not self._opening and not self._closed
                and time.monotonic() - self._failed_at >= self.RETRY_S):
            self._opening = True
            threading.Thread(target=self._try_open, name="device-open", daemon=True).start()
        return self._leds

    def _try_open(self) -> None:
        try:
            leds = self._open()
        except (OutputError, OSError, ValueError) as e:
            with self._lock:
                self._failed_at = time.monotonic()
                if self.error != str(e):
                    log.warning("%s", e)
                self.error, self._opening = str(e), False
            return
        with self._lock:
            self._opening = False
            if self._closed:
                leds.close()
                return
            self._leds, self.error = leds, None
            frame = self.frame if self.send else None
        if frame is not None and self.seq:
            leds.show(frame)  # catch up: the effect may have been playing meanwhile

    def _show(self, colors: np.ndarray) -> None:
        with self._lock:
            self.frame = colors.copy()
            self.seq += 1
            leds = self._leds_now() if self.send else None
        if leds is not None:
            leds.show(colors)

    def set_send(self, on: bool) -> None:
        """Send frames to the controller, or (off) keep them on the page only: the LEDs
        go dark."""
        with self._lock:
            self.send = on
            leds = self._leds_now()
        if leds is not None:
            leds.show(self.frame if on else np.zeros_like(self.frame))

    def close(self) -> None:
        with self._lock:
            leds, self._leds, self._closed = self._leds, None, True
        if leds is not None:
            leds.close()
