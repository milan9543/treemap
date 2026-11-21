from treemap.config import Config
from treemap.outputs.base import LedOutput, OutputError, TeeOutput


def create_output(cfg: Config, sim_port: int | None = None, source: str | None = None) -> LedOutput:
    """The ``LedOutput`` selected by ``cfg.output``. Raises ``OutputError`` if it can't
    be opened.

    The viewer (on ``sim_port``, default ``sim.port``) gets the frames either way: with
    ``output: wled`` it mirrors the real LEDs if it's open. ``source`` names the sender
    there (default: this command)."""
    from treemap.outputs.sim import SimOutput

    port = sim_port or cfg.sim.port
    if cfg.output == "sim":
        return SimOutput(cfg.led_count, host=cfg.sim.host, port=port, source=source)
    if cfg.output == "wled":
        from treemap.outputs.wled import WledOutput

        return TeeOutput(WledOutput(cfg.led_count, cfg.controllers),
                         SimOutput(cfg.led_count, host=cfg.sim.host, port=port, source=source,
                                   quiet=True))
    raise ValueError(f"unknown output {cfg.output!r}")


__all__ = ["LedOutput", "OutputError", "TeeOutput", "create_output"]
