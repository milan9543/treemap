"""The ``Camera`` interface: a stream of frames from a camera moving round the tree."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

import numpy as np


@dataclass
class Frame:
    t: float  # s, on the camera's own clock (only differences matter)
    image: np.ndarray  # (H, W, 3) uint8 BGR
    # Anything else the camera knows, e.g. its vertical field of view ("fov_v",
    # degrees), a starting guess for the solve. Never needed for the scan.
    meta: dict[str, Any] = field(default_factory=dict)


class Camera(ABC):
    """Frames arrive continuously; callers take them with :meth:`read`.

    Implementations override :meth:`_read`, and may queue a few frames when the caller
    is briefly busy (older frames are dropped beyond that).
    """

    def read(self, timeout: float) -> Frame | None:
        """The next frame, or None if none arrives within ``timeout`` seconds."""
        frame = self._read(timeout)
        if frame is None:
            return None
        img = frame.image
        if not isinstance(img, np.ndarray) or img.dtype != np.uint8 or img.ndim != 3 \
                or img.shape[2] != 3:
            raise ValueError(f"{type(self).__name__} returned a frame that isn't (H, W, 3) uint8")
        return frame

    def drain(self) -> None:
        """Drop any queued frames, so the next :meth:`read` is a fresh one."""
        while self._read(0) is not None:
            pass

    def close(self) -> None:
        """Release resources. Safe to call more than once."""

    @abstractmethod
    def _read(self, timeout: float) -> Frame | None:
        """Return the next frame, waiting up to ``timeout`` s, or None."""

    def __enter__(self) -> Camera:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
