"""Effects that show how good the tree map is (the viewer's Mapping panel)."""

from __future__ import annotations

import numpy as np

from treemap.effects.base import Effect, Param, ParamError
from treemap.effects.registry import register
from treemap.mapping.model import TreeMap
from treemap.mapping.quality import status_frame, verify_frame


class _MapEffect(Effect):
    group = "Mapping"

    def setup(self) -> None:
        if self._map() is None:
            raise ParamError("no tree map yet: run `treemap scan`, then `treemap reconstruct`")

    def _map(self) -> TreeMap | None:
        """The current map (reloaded if reconstruct rewrote it), if it fits these LEDs."""
        load = self.ctx.tree_map
        m = load() if load is not None else None
        if m is not None and m.led_count != self.n:
            raise ParamError(f"the tree map has {m.led_count} LEDs but led_count is {self.n}")
        return m


@register
class MapStatus(_MapEffect):
    name = "map-status"
    label = "Mapping quality"
    description = "Each LED by how well it was mapped: green ok, yellow interpolated, red failed."

    def render(self, t):
        m = self._map()
        return status_frame(m) if m is not None else self.blank()


@register
class MapVerify(_MapEffect):
    name = "map-verify"
    label = "Verify sweep"
    description = (
        "A plane rising through the mapped positions, then one sweeping left to right. "
        "An LED lighting out of step with its neighbours is mis-mapped."
    )
    params = (
        Param("seconds", "float", 6.0, min=1, max=30, step=0.5, help="seconds per sweep"),
        Param("band", "float", 0.05, min=0.01, max=0.2, step=0.01,
              help="plane half-thickness, fraction of the tree height"),
    )

    def render(self, t):
        m = self._map()
        if m is None:
            return self.blank()
        phase = (t / self.p["seconds"]) % 2.0
        return verify_frame(m, phase, self.p["band"]).astype(np.float32)
