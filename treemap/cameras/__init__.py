from __future__ import annotations

from typing import TYPE_CHECKING

from treemap.cameras.base import Camera, Frame

if TYPE_CHECKING:
    from treemap.config import Config


class CameraError(RuntimeError):
    """The configured camera can't be set up."""


def create_camera(cfg: Config, sim_port: int | None = None) -> Camera:
    """The ``Camera`` selected by ``cfg.camera.type``.

    ``sim`` is the viewer's virtual phone, relayed by the sim server on ``sim_port``
    (default ``sim.port``), so the viewer must be open.
    """
    if cfg.camera.type == "sim":
        from treemap.cameras.browser import BrowserCamera, CameraUnavailable

        try:
            return BrowserCamera(cfg.sim.host, sim_port or cfg.sim.port)
        except CameraUnavailable as e:
            raise CameraError(str(e)) from None
    if cfg.camera.type == "android":
        from treemap.cameras.android import AndroidCamera, CameraUnavailable

        try:
            return AndroidCamera(cfg.camera.url)
        except CameraUnavailable as e:
            raise CameraError(str(e)) from None
    raise ValueError(f"unknown camera {cfg.camera.type!r}")


__all__ = ["Camera", "CameraError", "Frame", "create_camera"]
