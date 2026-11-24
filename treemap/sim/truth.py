"""The virtual WLED's true LED positions as a tree map: what a perfect scan would find.

Scanning the virtual WLED means filming a screen, which works less well than filming
real LEDs. Its layout says exactly where every LED is, so the server can take that as
the device's map instead (``POST /devices/{id}/map/truth``) to try effects without a scan.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any

import numpy as np

from treemap.mapping.model import TreeMap, orient
from treemap.sim.flat import SimFlat
from treemap.sim.tree import SimTree

TIMEOUT_S = 5.0


def true_map(layout: dict[str, Any]) -> TreeMap:
    """The map of a layout as the virtual WLED's ``/api/layout`` gives it, in the map's
    frame (see :mod:`treemap.mapping.model`), every LED ``ok``. Raises ValueError or
    KeyError on a layout it can't read."""
    shape = "flat" if layout.get("shape") == "flat" else "tree"
    status = np.array(["ok"] * len(layout["positions"]), dtype="<U12")
    if shape == "flat":
        flat = SimFlat.from_dict(layout).positions
        # normalised as a flat scan is: y 0-1, x centred, facing as laid out
        positions = orient(flat, status, {"rotate_deg": 0, "mirror": False}, "flat")
    else:
        positions = SimTree.from_dict(layout).normalised_positions()
    meta = {"shape": shape, "source": "virtual WLED",
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return TreeMap(np.asarray(positions, dtype=float), status, meta)


def fetch_true_map(host: str, timeout: float = TIMEOUT_S) -> TreeMap:
    """The true map of the virtual WLED at ``host``. Raises OSError if it can't be
    reached, ValueError or KeyError if its reply isn't a layout."""
    with urllib.request.urlopen(f"http://{host}/api/layout", timeout=timeout) as r:
        layout = json.loads(r.read())
    if not isinstance(layout, dict):
        raise ValueError("its layout isn't an object")
    return true_map(layout)
