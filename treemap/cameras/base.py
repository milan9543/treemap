"""The ``Camera`` interface: anything that can take a fresh photo of the tree."""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType

import numpy as np


class Camera(ABC):
    """Captures still frames as OpenCV-style BGR images.

    Callers use :meth:`capture`; implementations override :meth:`_capture`. The frame
    must be *fresh*: taken after ``capture()`` was called, never a buffered older frame,
    because the scan lights one LED and immediately photographs it.
    """

    def capture(self) -> np.ndarray:
        """Return a fresh ``(H, W, 3)`` uint8 BGR frame."""
        frame = self._capture()
        if not isinstance(frame, np.ndarray):
            raise TypeError(f"{type(self).__name__} returned {type(frame).__name__}, not ndarray")
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(
                f"{type(self).__name__} returned a {frame.dtype} frame of shape {frame.shape}; "
                "expected (H, W, 3) uint8 BGR"
            )
        return frame

    def set_angle(self, angle_deg: float) -> bool:
        """Move to view angle ``angle_deg`` round the tree, if the camera can do it itself.

        Returns False when a person has to move it (a real camera on a tripod); the
        caller then asks them to. The angle convention is described in
        :mod:`treemap.cameras.sim`.
        """
        return False

    def close(self) -> None:
        """Release resources. Safe to call more than once."""

    @abstractmethod
    def _capture(self) -> np.ndarray:
        """Take a fresh photo and return it as an ``(H, W, 3)`` uint8 BGR array."""

    def __enter__(self) -> Camera:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
