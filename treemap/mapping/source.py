"""Which positions the position-aware effects use: the scanned map or the true tree.

``scanned`` is ``tree_map.json``, what the real tree will use. ``truth`` is the
simulator's ground truth in the same normalised frame, to compare an effect on the
perfect positions with the same effect on the scanned ones.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from treemap.mapping.model import MapFile, TreeMap

MAP_CHOICES = ("scanned", "truth")


class TruthFile:
    """The simulated tree at ``path`` as a :class:`TreeMap` (every LED ok), reloaded when
    the file changes. Calling it returns None if there isn't a readable tree."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._stamp: int | None = None
        self._map: TreeMap | None = None

    def __call__(self) -> TreeMap | None:
        from treemap.sim.tree import SimTree

        try:
            stamp = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            self._stamp, self._map = None, None
            return None
        if stamp != self._stamp:
            try:
                tree = SimTree.load(self.path)
                status = np.full(tree.led_count, "ok", dtype="<U12")
                self._map = TreeMap(tree.normalised_positions(), status, {"source": "truth"})
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                self._map = None
            self._stamp = stamp
        return self._map


class MapSource:
    """Calling it returns the selected map (or None). ``truth`` is only offered when a
    simulated tree file is given, i.e. in the simulator."""

    def __init__(self, map_path: str | Path, truth_path: str | Path | None = None,
                 choice: str = "scanned") -> None:
        self._loaders = {"scanned": MapFile(map_path)}
        if truth_path is not None:
            self._loaders["truth"] = TruthFile(truth_path)
        self.choice = "scanned"
        self.select(choice)

    @property
    def choices(self) -> list[str]:
        return list(self._loaders)

    def select(self, choice: str) -> None:
        if choice not in self._loaders:
            raise ValueError(f"map must be one of {', '.join(self._loaders)}, got {choice!r}")
        self.choice = choice

    def __call__(self) -> TreeMap | None:
        return self._loaders[self.choice]()

    def missing(self) -> str:
        """Why there's no map, and what to do about it."""
        if self.choice == "truth":
            return "no simulated tree yet: run `treemap sim new`"
        hint = (" (or use the true tree's positions: `--map truth`, or True tree in the viewer)"
                if "truth" in self._loaders else "")
        return f"no tree map yet: scan the tree first{hint}"
