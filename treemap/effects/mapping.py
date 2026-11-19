"""Effects that show how good the tree map is (the viewer's Mapping panel).

They override ``render`` rather than ``render_map``: an LED without a position still
shows its status colour.
"""

from __future__ import annotations

import numpy as np

from treemap.effects.base import MapEffect, Param
from treemap.effects.registry import register
from treemap.mapping.quality import status_frame, verify_frame


class _MappingEffect(MapEffect):
    group = "Mapping"


@register
class MapStatus(_MappingEffect):
    name = "map-status"
    label = "Mapping quality"
    description = "Each LED by how well it was mapped: green ok, yellow interpolated, red failed."

    def render(self, t):
        m = self.tree_map()
        return status_frame(m) if m is not None else self.blank()


@register
class MapVerify(_MappingEffect):
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
        m = self.tree_map()
        if m is None:
            return self.blank()
        phase = (t / self.p["seconds"]) % 2.0
        return verify_frame(m, phase, self.p["band"]).astype(np.float32)
