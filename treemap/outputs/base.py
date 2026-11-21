"""The ``LedOutput`` interface: anything that can display a frame of LED colours."""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType

import numpy as np


class OutputError(RuntimeError):
    """The output can't be opened (e.g. a WLED controller's name doesn't resolve)."""


class LedOutput(ABC):
    """Displays colours on ``led_count`` LEDs, indexed globally 0..led_count-1.

    Callers use :meth:`show`; implementations override :meth:`_show`, which receives an
    already-validated, C-contiguous ``(led_count, 3)`` uint8 RGB array.
    """

    def __init__(self, led_count: int) -> None:
        if led_count < 1:
            raise ValueError(f"led_count must be >= 1, got {led_count}")
        self.led_count = led_count

    def show(self, colors: np.ndarray) -> None:
        """Display one frame. ``colors`` is an ``(led_count, 3)`` uint8 RGB array."""
        arr = np.asarray(colors)
        if arr.dtype != np.uint8:
            raise TypeError(
                f"colors must be uint8, got {arr.dtype} "
                "(convert explicitly, e.g. np.clip(x, 0, 255).astype(np.uint8))"
            )
        if arr.shape != (self.led_count, 3):
            raise ValueError(f"colors must have shape ({self.led_count}, 3), got {arr.shape}")
        self._show(np.ascontiguousarray(arr))

    def fill(self, rgb: tuple[int, int, int]) -> None:
        """Set every LED to the same colour."""
        self.show(np.tile(np.asarray(rgb, dtype=np.uint8), (self.led_count, 1)))

    def off(self) -> None:
        """Turn every LED off."""
        self.show(np.zeros((self.led_count, 3), dtype=np.uint8))

    def close(self) -> None:
        """Release resources. Safe to call more than once."""

    @abstractmethod
    def _show(self, colors: np.ndarray) -> None:
        """Send a validated ``(led_count, 3)`` uint8 frame to the device."""

    def __enter__(self) -> LedOutput:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
