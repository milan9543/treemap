from __future__ import annotations

from typing import TYPE_CHECKING

from treemap.cameras.base import Camera

if TYPE_CHECKING:
    from treemap.config import Config
    from treemap.outputs.base import LedOutput


class CameraError(RuntimeError):
    """The configured camera can't be set up."""


def create_camera(cfg: Config, output: LedOutput | None = None) -> Camera:
    """The ``Camera`` selected by ``cfg.camera.type``.

    The sim camera photographs the simulated tree, so it needs the ``SimOutput`` whose
    colours it should render.
    """
    if cfg.camera.type == "sim":
        from treemap.cameras.sim import SimCamera
        from treemap.outputs.sim import SimOutput
        from treemap.sim.tree import SimTree

        if not isinstance(output, SimOutput):
            raise CameraError("camera: sim photographs the simulated tree, so it needs output: sim")
        try:
            tree = SimTree.load(cfg.sim_tree_path)
        except FileNotFoundError:
            raise CameraError(
                f"no simulated tree at {cfg.sim_tree_path}; run `treemap sim new`"
            ) from None
        if tree.led_count != output.led_count:
            raise CameraError(
                f"the simulated tree has {tree.led_count} LEDs but led_count is "
                f"{output.led_count}; run `treemap sim new`"
            )
        return SimCamera(tree, lambda: output.last_frame)
    if cfg.camera.type == "android":
        raise NotImplementedError("the Android camera arrives in Batch 9; use `camera: sim`")
    raise ValueError(f"unknown camera {cfg.camera.type!r}")


__all__ = ["Camera", "CameraError", "create_camera"]
