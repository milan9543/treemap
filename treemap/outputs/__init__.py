from treemap.config import Config
from treemap.outputs.base import LedOutput


def create_output(cfg: Config) -> LedOutput:
    """The ``LedOutput`` selected by ``cfg.output``."""
    if cfg.output == "sim":
        from treemap.outputs.sim import SimOutput

        return SimOutput(cfg.led_count, host=cfg.sim.host, port=cfg.sim.port)
    if cfg.output == "wled":
        raise NotImplementedError("WLED output arrives in Batch 8; use `output: sim` for now")
    raise ValueError(f"unknown output {cfg.output!r}")


__all__ = ["LedOutput", "create_output"]
