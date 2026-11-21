"""``HttpCamera``: frames the phone's page uploads to ``treemap serve``.

The page films the LEDs, encodes JPEGs in a worker and POSTs them about four times a
second to ``/api/v1/scan/frames`` (see :mod:`treemap.api`), which hands each batch to
:meth:`HttpCamera.push`. The scan reads them through the ordinary ``Camera`` interface.

A batch is frames back to back, each a 4-byte little-endian length followed by exactly
what :func:`treemap.cameras.browser.pack_frame` makes (header length, JSON header with
``t`` in seconds on the phone's clock, JPEG). Frames are decoded only when read, so a
batch is accepted quickly even while the scan is busy.
"""

from __future__ import annotations

import collections
import json
import logging
import struct
import threading
import time

from treemap.cameras.base import Camera, Frame
from treemap.cameras.browser import pack_frame, unpack_frame

log = logging.getLogger(__name__)

QUEUE = 48  # frames kept while the scan is busy; older ones are dropped
MAX_FRAME = 4 * 2**20  # bytes; a 720p JPEG is about 100 KB


class BatchError(ValueError):
    """A frame batch that isn't in the expected format."""


def pack_batch(frames: list[tuple[dict, bytes]]) -> bytes:
    """``(header, jpeg)`` pairs as one upload body (for tests and scripts)."""
    out = bytearray()
    for header, jpeg in frames:
        f = pack_frame(header, jpeg)
        out += struct.pack("<I", len(f)) + f
    return bytes(out)


def split_batch(body: bytes) -> list[bytes]:
    """An upload body as packed frames. Raises :class:`BatchError`."""
    frames, i = [], 0
    while i < len(body):
        if i + 4 > len(body):
            raise BatchError("the batch ends inside a frame length")
        (n,) = struct.unpack_from("<I", body, i)
        i += 4
        if not 4 < n <= MAX_FRAME or i + n > len(body):
            raise BatchError(f"frame length {n} doesn't fit the batch")
        frames.append(body[i:i + n])
        i += n
    return frames


class HttpCamera(Camera):
    def __init__(self) -> None:
        self._queue: collections.deque[bytes] = collections.deque(maxlen=QUEUE)
        self._ready = threading.Condition()
        self.received = 0  # frames pushed so far
        self.last_push = 0.0  # time.monotonic() of the latest batch

    def push(self, body: bytes) -> int:
        """Queue a batch's frames; returns how many. Raises :class:`BatchError`."""
        frames = split_batch(body)
        with self._ready:
            self._queue.extend(frames)
            self.received += len(frames)
            self.last_push = time.monotonic()
            self._ready.notify_all()
        return len(frames)

    def _read(self, timeout: float) -> Frame | None:
        with self._ready:
            if not self._queue and timeout > 0:
                self._ready.wait(timeout)
            if not self._queue:
                return None
            data = self._queue.popleft()
        try:
            return unpack_frame(data)
        except (ValueError, struct.error, json.JSONDecodeError, KeyError) as e:
            log.warning("dropped a bad frame from the phone: %s", e)
            return None

    def drain(self) -> None:
        with self._ready:
            self._queue.clear()
