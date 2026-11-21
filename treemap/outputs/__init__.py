from treemap.config import Config
from treemap.outputs.base import LedOutput, OutputError


def create_output(cfg: Config) -> LedOutput:
    """The ``LedOutput`` selected by ``cfg.output``. Raises ``OutputError`` if it can't
    be opened."""
    if cfg.output == "sim":
        from treemap.outputs.sim import SimOutput

        return SimOutput(cfg.led_count, host=cfg.sim.host, port=cfg.sim.port)
    if cfg.output == "wled":
        from treemap.outputs.wled import WledOutput

        return WledOutput(cfg.led_count, cfg.controllers)
    raise ValueError(f"unknown output {cfg.output!r}")


__all__ = ["LedOutput", "OutputError", "create_output"]
