"""``BrowserCamera``: photos from the viewer's virtual phone.

The viewer renders what its camera sees (you walk round the simulated tree with WASD
and the mouse) and sends each photo to the sim server on ``/ws/camera?role=phone``.
The server relays them to every scanner connected on ``/ws/camera?role=scan``, which is
what this class is. Scanners send JSON back (``{"type": "detections", ...}``), which the
server passes on to the viewers for the phone inset.

Wire format of a frame: a 4-byte little-endian header length, the header as UTF-8
JSON (``t`` in seconds on the browser's clock, ``fov_v`` in degrees, ``eye``, ``quat``),
then the JPEG.
"""

from __future__ import annotations

import collections
import json
import logging
import struct
import threading
from contextlib import ExitStack

import cv2
import numpy as np
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI
from websockets.sync.client import ClientConnection, connect

from treemap.cameras.base import Camera, Frame

log = logging.getLogger(__name__)

CAMERA_PATH = "/ws/camera"
QUEUE = 48  # frames kept while the scan is busy; older ones are dropped


class CameraUnavailable(RuntimeError):
    pass


def pack_frame(header: dict, jpeg: bytes) -> bytes:
    h = json.dumps(header).encode()
    return struct.pack("<I", len(h)) + h + jpeg


def unpack_frame(data: bytes) -> Frame:
    (n,) = struct.unpack_from("<I", data)
    header = json.loads(data[4:4 + n])
    img = cv2.imdecode(np.frombuffer(data, np.uint8, offset=4 + n), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("frame isn't a decodable image")
    return Frame(float(header.pop("t")), img, header)


class BrowserCamera(Camera):
    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.url = f"ws://{host}:{port}{CAMERA_PATH}?role=scan"
        self._stack = ExitStack()
        try:
            self._ws: ClientConnection = self._stack.enter_context(
                connect(self.url, open_timeout=2.0, compression=None, max_size=2**23)
            )
        except (OSError, TimeoutError, InvalidHandshake, InvalidURI) as e:
            raise CameraUnavailable(
                f"the viewer's camera isn't reachable at {self.url} ({e}); "
                "start `treemap sim view` and keep the viewer open"
            ) from None
        self._queue: collections.deque[bytes] = collections.deque(maxlen=QUEUE)
        self._ready = threading.Condition()
        self._closed = False
        self._thread = threading.Thread(target=self._receive, name="browser-camera", daemon=True)
        self._thread.start()

    def _receive(self) -> None:
        try:
            for message in self._ws:
                if isinstance(message, bytes):
                    with self._ready:
                        self._queue.append(message)
                        self._ready.notify()
        except (ConnectionClosed, OSError):
            pass
        finally:
            with self._ready:
                self._closed = True
                self._ready.notify_all()

    def _read(self, timeout: float) -> Frame | None:
        with self._ready:
            if not self._queue and not self._closed and timeout > 0:
                self._ready.wait(timeout)
            if not self._queue:
                if self._closed:
                    raise CameraUnavailable("lost the connection to the viewer")
                return None
            data = self._queue.popleft()
        try:
            return unpack_frame(data)
        except (ValueError, struct.error, json.JSONDecodeError, KeyError) as e:
            log.warning("dropped a bad camera frame: %s", e)
            return None

    def drain(self) -> None:
        with self._ready:
            self._queue.clear()

    def show_detections(self, data: dict) -> None:
        try:
            self._ws.send(json.dumps({"type": "detections", **data}))
        except (ConnectionClosed, OSError):
            pass

    def close(self) -> None:
        stack, self._stack = self._stack, ExitStack()
        stack.close()
