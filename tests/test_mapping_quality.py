import os

import numpy as np

from treemap.mapping.model import MapFile, TreeMap
from treemap.mapping.quality import STATUS_COLORS, status_frame


def small_map():
    y = np.linspace(0, 1, 5)
    P = np.stack([np.linspace(-0.4, 0.4, 5), y, np.zeros(5)], axis=1)
    P[4] = np.nan
    status = np.array(["ok", "ok", "interpolated", "ok", "failed"])
    return TreeMap(P, status)


def test_status_frame():
    frame = status_frame(small_map())
    assert tuple(frame[0]) == STATUS_COLORS["ok"]
    assert tuple(frame[2]) == STATUS_COLORS["interpolated"]
    assert tuple(frame[4]) == STATUS_COLORS["failed"]


def test_the_map_file_reloads_when_a_scan_changes_it(tmp_path):
    path = tmp_path / "tree_map.json"
    load = MapFile(path)
    assert load() is None

    small_map().save(path)
    assert load().status[2] == "interpolated"

    changed = small_map()
    changed.status[2] = "ok"
    changed.save(path)
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 10**9))  # make sure the stamp changes
    assert load().status[2] == "ok"
