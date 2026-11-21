"""``SimOutput``: streams colour frames to the browser viewer via the sim server."""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import ExitStack
from urllib.parse import quote

import numpy as np
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI
from websockets.sync.client import ClientConnection, connect

from treemap.outputs.base import LedOutput

log = logging.getLogger(__name__)

OUTPUT_PATH = "/ws/output"


def default_source() -> str:
    """This program as the viewer should name it, e.g. ``treemap show-mapping (pid 123)``."""
    args = [a for a in sys.argv[1:] if not a.startswith("-")][:3]
    return f"treemap {' '.join(args)}".strip() + f" (pid {os.getpid()})"


class SimOutput(LedOutput):
    """Sends each frame as raw RGB bytes to ``ws://host:port/ws/output``.

    The viewer is optional: if the server isn't running, frames are still accepted (and
    kept in :attr:`last_frame` for the simulated camera), and the connection is retried
    every ``retry_s`` seconds.
    """

    def __init__(
        self, led_count: int, host: str = "127.0.0.1", port: int = 8765, retry_s: float = 2.0,
        source: str | None = None, quiet: bool = False,
    ) -> None:
        super().__init__(led_count)
        self.quiet = quiet  # don't warn when the viewer isn't running (it's optional)
        # Shown in the viewer when several programs send frames at once.
        self.source = source or default_source()
        self.url = f"ws://{host}:{port}{OUTPUT_PATH}?source={quote(self.source)}"
        self.retry_s = retry_s
        self.last_frame = np.zeros((led_count, 3), dtype=np.uint8)
        self._ws: ClientConnection | None = None
        self._stack: ExitStack | None = None
        self._next_attempt = 0.0
        self._warned = False

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def _show(self, colors: np.ndarray) -> None:
        self.last_frame = colors.copy()
        ws = self._connection()
        if ws is None:
            return
        try:
            ws.send(colors.tobytes())
        except (ConnectionClosed, OSError):
            log.warning("lost connection to the sim viewer at %s", self.url)
            self._drop()

    def _connection(self) -> ClientConnection | None:
        if self._ws is not None:
            return self._ws
        now = time.monotonic()
        if now < self._next_attempt:
            return None
        try:
            stack = ExitStack()
            self._ws = stack.enter_context(connect(self.url, open_timeout=1.0, compression=None))
            self._stack = stack
        except (OSError, TimeoutError, InvalidHandshake, InvalidURI) as e:
            self._next_attempt = now + self.retry_s
            if not self._warned and not self.quiet:
                log.warning(
                    "sim viewer not reachable at %s (%s); start it with `treemap sim view`",
                    self.url,
                    e,
                )
                self._warned = True
            return None
        if self._warned:
            log.warning("connected to the sim viewer at %s", self.url)
        self._warned = False
        return self._ws

    def _drop(self) -> None:
        self.close()
        self._next_attempt = time.monotonic() + self.retry_s

    def close(self) -> None:
        stack, self._stack, self._ws = self._stack, None, None
        if stack is not None:
            try:
                stack.close()
            except Exception:  # noqa: BLE001 - already broken, nothing useful to do
                pass
