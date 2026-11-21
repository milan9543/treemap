"""``AndroidCamera``: video from the IP Webcam Android app, over Wi-Fi.

IP Webcam serves an MJPEG stream at ``{url}/video``: JPEG after JPEG in one endless HTTP
response. A background thread reads it, cuts out each JPEG (from its start marker
FF D8 to its end marker FF D9) and timestamps it on arrival. Stream lag doesn't matter
to the scan, which decodes from colour changes, not from the LEDs' clock. If the stream
drops (Wi-Fi), the thread reconnects.

The app's settings are read from ``{url}/status.json`` and changed with
``{url}/settings/<key>?set=<value>``; the scan needs exposure and white balance locked
(``exposure_lock``, ``whitebalance_lock``), so colours don't drift while the LEDs flash.
"""

from __future__ import annotations

import collections
import http.client
import logging
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import cv2
import numpy as np

from treemap.cameras.base import Camera, Frame

log = logging.getLogger(__name__)

QUEUE = 48  # frames kept while the scan is busy; older ones are dropped
MAX_BUFFER = 8 * 2**20  # bytes without a complete JPEG before the buffer is reset
SOI, EOI = b"\xff\xd8", b"\xff\xd9"


class CameraUnavailable(RuntimeError):
    pass


def split_jpegs(buf: bytearray) -> list[bytes]:
    """Cut the complete JPEGs out of the front of ``buf`` (in place), keeping the rest."""
    out = []
    while True:
        a = buf.find(SOI)
        if a < 0:
            del buf[:-1]  # keep a last FF: it may start the next marker
            return out
        b = buf.find(EOI, a + 2)
        if b < 0:
            del buf[:a]
            return out
        out.append(bytes(buf[a:b + 2]))
        del buf[:b + 2]


class AndroidCamera(Camera):
    def __init__(self, url: str, connect_timeout: float = 5.0) -> None:
        parts = urlsplit(url if "://" in url else f"http://{url}")
        if parts.scheme != "http" or not parts.hostname:
            raise CameraUnavailable(f"camera.url must look like http://192.168.1.60:8080, not {url!r}")
        self.url = f"http://{parts.netloc}{parts.path.rstrip('/')}"
        self._host, self._port = parts.hostname, parts.port or 80
        self._path = parts.path.rstrip("/")
        self._queue: collections.deque[tuple[float, bytes]] = collections.deque(maxlen=QUEUE)
        self._ready = threading.Condition()
        self._closed = threading.Event()
        self._first = threading.Event()
        self._conn: http.client.HTTPConnection | None = None
        self.error: str | None = None  # the latest connection problem, if any
        self._thread = threading.Thread(target=self._run, name="android-camera", daemon=True)
        self._thread.start()
        if not self._first.wait(connect_timeout):
            reason = self.error or f"no frames within {connect_timeout:g} s"
            self.close()
            raise CameraUnavailable(
                f"no video from {self.url}/video ({reason}). Is IP Webcam running (Start "
                "server) and the phone on the same Wi-Fi? Its address is shown at the bottom "
                "of the phone's screen."
            )

    # -- the stream (background thread) ---------------------------------------------

    def _run(self) -> None:
        while not self._closed.is_set():
            try:
                self._stream()
            except (OSError, http.client.HTTPException) as e:
                if not self._closed.is_set():
                    if self.error is None and self._first.is_set():  # else __init__ says
                        log.warning("lost the camera stream from %s (%s); reconnecting",
                                    self.url, e)
                    self.error = str(e) or type(e).__name__
            self._closed.wait(1.0)

    def _stream(self) -> None:
        conn = http.client.HTTPConnection(self._host, self._port, timeout=5)
        self._conn = conn
        try:
            conn.request("GET", f"{self._path}/video")
            resp = conn.getresponse()
            if resp.status != 200:
                raise OSError(f"HTTP {resp.status} {resp.reason}")
            buf = bytearray()
            while not self._closed.is_set():
                chunk = resp.read1(65536)
                if not chunk:
                    raise OSError("the stream ended")
                buf += chunk
                jpegs = split_jpegs(buf)
                if len(buf) > MAX_BUFFER:
                    buf.clear()
                if jpegs:
                    now = time.monotonic()
                    with self._ready:
                        self._queue.extend((now, j) for j in jpegs)
                        self._ready.notify()
                    if self.error is not None:
                        log.warning("camera stream from %s is back", self.url)
                    self.error = None
                    self._first.set()
        finally:
            conn.close()

    # -- Camera ------------------------------------------------------------------------

    def _read(self, timeout: float) -> Frame | None:
        with self._ready:
            if not self._queue and timeout > 0:
                self._ready.wait(timeout)
            if not self._queue:
                return None
            t, jpeg = self._queue.popleft()
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            log.warning("dropped a camera frame that isn't a decodable JPEG")
            return None
        return Frame(t, img)

    def drain(self) -> None:
        with self._ready:
            self._queue.clear()

    def close(self) -> None:
        self._closed.set()
        conn = self._conn
        if conn is not None and conn.sock is not None:
            try:
                conn.sock.shutdown(2)  # wakes the reader blocked in read1
            except OSError:
                pass
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    # -- the app's settings ------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        """The app's current settings (``curvals`` of ``/status.json``), {} if unreadable."""
        import requests

        try:
            r = requests.get(f"{self.url}/status.json", timeout=3)
            r.raise_for_status()
            return dict(r.json().get("curvals") or {})
        except (requests.RequestException, ValueError, AttributeError):
            return {}

    def set(self, key: str, value: str) -> bool:
        """Change one of the app's settings; True if the app accepted it."""
        import requests

        try:
            r = requests.get(f"{self.url}/settings/{key}", params={"set": value}, timeout=3)
            return r.ok
        except requests.RequestException:
            return False

    # IP Webcam has two kinds of camera settings. With the older Android camera API it has
    # exposure_lock and whitebalance_lock. With the newer one (most phones now) it has
    # neither: exposure stays put while manual_sensor is on (switching it on freezes what
    # auto exposure had chosen), and white balance while it's a preset rather than auto.

    def locked(self) -> bool | None:
        """Whether exposure and white balance are both fixed; None if unknown."""
        s = self.settings()
        if "exposure_lock" in s:
            return s["exposure_lock"] == "on" and s.get("whitebalance_lock") == "on"
        if "manual_sensor" in s:
            return s["manual_sensor"] == "on" and s.get("whitebalance", "auto") != "auto"
        return None

    def lock(self, on: bool = True) -> bool:
        """Fix (or free) exposure and white balance; True if the app accepted both."""
        s = self.settings()
        if "manual_sensor" in s and "exposure_lock" not in s:
            return all([self.set("manual_sensor", "on" if on else "off"),
                         self.set("whitebalance", "daylight" if on else "auto")])
        value = "on" if on else "off"
        return all([self.set("exposure_lock", value), self.set("whitebalance_lock", value)])
