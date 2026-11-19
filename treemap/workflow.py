"""The mapping workflow (scan, reconstruct, fix, evaluate) as plain functions.

Both the command line and the viewer's server drive the same steps through here; they
differ only in how they report progress and ask a person to move the camera.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from treemap.config import Config, parse_leds

if TYPE_CHECKING:
    from treemap.mapping.model import TreeMap
    from treemap.outputs.base import LedOutput
    from treemap.scan.capture import AngleScan
    from treemap.scan.evaluate import Evaluation
    from treemap.scan.reconstruct import Reconstruction


class WorkflowError(RuntimeError):
    """A step can't run; the message says why and what to do."""


def default_settle_ms(cfg: Config) -> int:
    """The sim camera sees the LEDs instantly; a real one needs ``scan.settle_ms``."""
    return 0 if cfg.camera.type == "sim" else cfg.scan.settle_ms


def parse_led_subset(text: str | None, led_count: int) -> list[int] | None:
    if text is None or not str(text).strip():
        return None
    try:
        return parse_leds(str(text), led_count)
    except ValueError as e:
        raise WorkflowError(f"LEDs: {e}") from None


def ensure_sim_tree(cfg: Config) -> bool:
    """Generate a simulated tree if the sim camera needs one; True if it did."""
    if cfg.camera.type != "sim" or cfg.sim_tree_path.exists():
        return False
    from treemap.sim.tree import generate_tree, spec_from_config

    generate_tree(spec_from_config(cfg)).save(cfg.sim_tree_path)
    return True


def run_scan(
    cfg: Config,
    output: LedOutput,
    angles: list[float],
    leds: list[int] | None,
    *,
    fresh: bool = False,
    settle_ms: int | None = None,
    flash_s: float = 1.5,
    ask_to_move: Callable[[float], None] = lambda angle: None,
    on_progress: Callable[[float, int, int, int, dict], None] | None = None,
    on_angle: Callable[[float, AngleScan], None] | None = None,
) -> list[AngleScan]:
    """Scan ``leds`` (None: every LED not yet done) at each angle.

    Before each angle the camera moves itself, or ``ask_to_move(angle)`` is called and
    should return once a person has moved it. Interrupting (any exception from a
    callback) keeps what was scanned so far.
    """
    from treemap.cameras import CameraError, create_camera
    from treemap.scan.capture import ScanError, scan_angle

    settle_ms = default_settle_ms(cfg) if settle_ms is None else settle_ms
    try:
        camera = create_camera(cfg, output)
    except (CameraError, NotImplementedError) as e:
        raise WorkflowError(str(e)) from None
    results = []
    with camera:
        for angle in angles:
            if not camera.set_angle(angle):
                ask_to_move(angle)

            def progress(done: int, total: int, i: int, entry: dict, a: float = angle) -> None:
                if on_progress:
                    on_progress(a, done, total, i, entry)

            try:
                result = scan_angle(
                    output, camera, angle, cfg.scan_dir, leds=leds, fresh=fresh,
                    settle_s=settle_ms / 1000, brightness=cfg.scan.brightness,
                    min_confidence=cfg.scan.min_confidence, flash_s=flash_s,
                    on_progress=progress,
                )
            except ScanError as e:
                raise WorkflowError(str(e)) from None
            results.append(result)
            if on_angle:
                on_angle(angle, result)
    return results


def coverage(cfg: Config) -> dict:
    """How many LEDs the saved scans found in 2+ views, and in none."""
    from treemap.scan.capture import load_scans

    n = cfg.led_count
    scans = [s for s in load_scans(cfg.scan_dir) if s.led_count == n]
    seen = np.zeros(n, dtype=int)
    for s in scans:
        seen[s.ok_indices()] += 1
    return {"angles": len(scans), "two_plus": int((seen >= 2).sum()),
            "none": int((seen == 0).sum()), "led_count": n}


def rebuild_map(cfg: Config) -> tuple[TreeMap, Reconstruction, list[AngleScan]]:
    """Reconstruct from the saved scans (honouring ``fix`` overrides) and save the map."""
    from treemap.scan.capture import ScanError, load_overrides, load_scans
    from treemap.scan.reconstruct import ReconstructionError, build_map

    try:
        scans = load_scans(cfg.scan_dir)
        tree_map, rec = build_map(scans, cfg.led_count, load_overrides(cfg.scan_dir))
    except (ScanError, ReconstructionError) as e:
        raise WorkflowError(f"can't reconstruct from {cfg.scan_dir}: {e}") from None
    tree_map.save(cfg.map_path)
    return tree_map, rec, scans


def reconstruction_summary(tree_map: TreeMap, rec: Reconstruction, scans: list[AngleScan]) -> dict:
    return {
        "angles": [s.angle for s in scans],
        "angle_offsets": [round(float(o), 2) for o in rec.angle_offsets],
        "median_residual_px": rec.info["median_residual_px"],
        "focal_px": round(rec.focal, 1),
        "counts": tree_map.counts(),
        "outliers": tree_map.meta.get("outliers", []),
    }


def load_map(cfg: Config) -> TreeMap:
    from treemap.mapping.model import TreeMap

    try:
        tree_map = TreeMap.load(cfg.map_path)
    except FileNotFoundError:
        raise WorkflowError(
            f"no tree map at {cfg.map_path}: scan, then reconstruct"
        ) from None
    except (ValueError, KeyError) as e:
        raise WorkflowError(f"{cfg.map_path}: {e}") from None
    if tree_map.led_count != cfg.led_count:
        raise WorkflowError(
            f"the tree map has {tree_map.led_count} LEDs but led_count is {cfg.led_count}; "
            "scan and reconstruct again"
        )
    return tree_map


def set_interpolate(cfg: Config, index: int, interpolate: bool) -> None:
    """Make reconstruct ignore LED ``index``'s detections (or use them again)."""
    from treemap.scan.capture import load_overrides, save_overrides

    _check_index(cfg, index)
    overrides = load_overrides(cfg.scan_dir)
    if interpolate:
        overrides.add(index)
    else:
        overrides.discard(index)
    save_overrides(cfg.scan_dir, overrides)


def rescan_led(
    cfg: Config, output: LedOutput, index: int, angles: list[float] | None = None,
    **scan_kwargs,
) -> list[AngleScan]:
    """Photograph one LED again (at every scanned angle by default) and drop any
    interpolate override, so reconstruct measures it."""
    from treemap.scan.capture import load_scans

    _check_index(cfg, index)
    angles = angles or [s.angle for s in load_scans(cfg.scan_dir)] or cfg.scan.angles
    results = run_scan(cfg, output, angles, [index], flash_s=0.0, **scan_kwargs)
    set_interpolate(cfg, index, False)
    return results


def evaluate_sim(cfg: Config) -> Evaluation:
    """Compare the map with the simulated tree's true positions."""
    from treemap.scan.evaluate import evaluate
    from treemap.sim.tree import SimTree

    tree_map = load_map(cfg)
    try:
        tree = SimTree.load(cfg.sim_tree_path)
        return evaluate(tree_map, tree)
    except FileNotFoundError:
        raise WorkflowError(f"no simulated tree at {cfg.sim_tree_path}") from None
    except (ValueError, KeyError) as e:
        raise WorkflowError(str(e)) from None


def evaluation_summary(ev: Evaluation) -> dict:
    return {
        "height_m": round(ev.height_m, 3),
        "rotation_deg": round(ev.rotation_deg, 2),
        "scale": round(ev.scale, 4),
        "rows": [{"status": name, **s} for name, s in ev.table()],
    }


def scan_index(cfg: Config) -> list[dict]:
    """The saved scans for the viewer: per angle, counts, image files and detections."""
    from treemap.scan.capture import angle_name, load_scans

    out = []
    for s in load_scans(cfg.scan_dir):
        stem = angle_name(s.angle)
        images = {}
        for kind in ("debug", "exposure", "dark"):
            p = cfg.scan_dir / f"{stem}_{kind}.png"
            if p.exists():
                images[kind] = {"name": p.name, "stamp": p.stat().st_mtime_ns}
        out.append({
            "angle": s.angle, "name": stem, "led_count": s.led_count,
            "counts": s.counts(), "images": images,
            "leds": {str(i): e for i, e in sorted(s.leds.items())},
        })
    return out


def scan_image_path(cfg: Config, name: str) -> Path | None:
    """The scan image called ``name``, if it's one (never anything else on disk)."""
    import re

    if not re.fullmatch(r"angle_\d{3}_(debug|exposure|dark)\.png", name):
        return None
    path = cfg.scan_dir / name
    return path if path.is_file() else None


def _check_index(cfg: Config, index: int) -> None:
    if not 0 <= index < cfg.led_count:
        raise WorkflowError(f"LED index must be 0-{cfg.led_count - 1}, got {index}")
