"""The mapping workflow (scan, reconstruct, fix, evaluate) as plain functions.

Both the command line and the viewer's server drive the same steps through here; they
differ only in how they report progress.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from treemap.config import Config, parse_leds

if TYPE_CHECKING:
    from treemap.mapping.model import TreeMap
    from treemap.outputs.base import LedOutput
    from treemap.scan.evaluate import Evaluation
    from treemap.scan.colours import ColourModel
    from treemap.scan.free import ScanSettings
    from treemap.scan.sfm import SfmResult


class WorkflowError(RuntimeError):
    """A step can't run; the message says why and what to do."""


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


def camera_colours(cfg: Config) -> tuple[ColourModel | None, str | None]:
    """The configured camera's measured colours (from ``treemap camera check``), and if
    there aren't any usable, why: ``(None, message)``. The sim camera's colours are pure
    enough not to need them."""
    from treemap.scan.colours import ColourError, ColourModel

    path = cfg.colours_path
    if not path.exists():
        return None, (None if cfg.camera.type == "sim" else
                      "this camera's colours haven't been measured: run `treemap camera "
                      "check` first, or colours may be misread")
    try:
        model = ColourModel.load(path)
    except ColourError as e:
        return None, f"ignoring the measured colours: {e}"
    if model.meta.get("camera") != cfg.camera_id:
        return None, (f"the measured colours are for another camera "
                      f"({model.meta.get('camera')}); run `treemap camera check` again")
    measured_at = model.meta.get("brightness")
    if measured_at not in (None, cfg.scan.brightness):
        return model, (f"the colours were measured at brightness {measured_at}, the scan "
                       f"flashes at {cfg.scan.brightness}; if colours misread, run "
                       "`treemap camera check` again")
    return model, None


def scan_settings(cfg: Config, colours: ColourModel | None = None) -> ScanSettings:
    from treemap.scan.free import ScanSettings

    s = cfg.scan
    return ScanSettings(
        led_count=cfg.led_count, scan_dir=cfg.scan_dir, map_path=cfg.map_path,
        symbol_s=s.symbol_ms / 1000, brightness=s.brightness, round_s=s.round_s,
        status_s=s.status_s, max_rounds=s.max_rounds, fov_deg=cfg.camera.fov_deg,
        colours=colours,
    )


def run_scan(
    cfg: Config,
    output: LedOutput,
    *,
    fresh: bool = False,
    rounds: int | None = None,
    sim_port: int | None = None,
    on_update: Callable[[dict], None] = lambda u: None,
    check_cancel: Callable[[], None] = lambda: None,
    on_message: Callable[[str], None] = lambda m: None,
) -> TreeMap | None:
    """Scan in rounds (see :mod:`treemap.scan.free`) with the configured camera.

    A camera that can lock its exposure and white balance (the Android one) gets them
    locked on the LEDs first, unless they already are. Interrupting (any exception from
    a callback) keeps the rounds finished so far.
    """
    from treemap.cameras import CameraError, create_camera
    from treemap.cameras.browser import CameraUnavailable
    from treemap.cameras.check import settle_and_lock
    from treemap.scan.free import ScanError, scan

    try:
        camera = create_camera(cfg, sim_port)
    except (CameraError, NotImplementedError) as e:
        raise WorkflowError(str(e)) from None
    colours, problem = camera_colours(cfg)
    if problem:
        on_message(problem)
    with camera:
        if hasattr(camera, "locked") and not camera.locked():
            on_message("locking the camera's exposure and white balance on the LEDs…")
            if not settle_and_lock(camera, output, cfg.scan.brightness):
                on_message("couldn't lock them; lock exposure and white balance in IP Webcam")
        try:
            return scan(output, camera, scan_settings(cfg, colours), fresh=fresh, rounds=rounds,
                        on_update=on_update, check_cancel=check_cancel)
        except (ScanError, CameraUnavailable) as e:
            raise WorkflowError(str(e)) from None


def rebuild_map(cfg: Config) -> tuple[TreeMap, SfmResult]:
    """Solve again from the saved rounds (honouring ``fix`` overrides) and save the map."""
    from treemap.scan.free import ScanError, build_map, load_overrides, load_rounds
    from treemap.scan.sfm import SfmError

    try:
        tree_map, res = build_map(load_rounds(cfg.scan_dir), cfg.led_count,
                                  load_overrides(cfg.scan_dir))
    except (ScanError, SfmError) as e:
        raise WorkflowError(f"can't reconstruct from {cfg.scan_dir}: {e}") from None
    tree_map.save(cfg.map_path)
    return tree_map, res


def map_summary(tree_map: TreeMap) -> dict:
    m = tree_map.meta
    return {
        "counts": tree_map.counts(),
        "rounds": m.get("rounds"),
        "registered": m.get("registered"),
        "median_residual_px": m.get("median_residual_px"),
        "focal_px": m.get("focal_px"),
        "outliers": m.get("outliers", []),
    }


def load_map(cfg: Config) -> TreeMap:
    from treemap.mapping.model import TreeMap

    try:
        tree_map = TreeMap.load(cfg.map_path)
    except FileNotFoundError:
        raise WorkflowError(
            f"no tree map at {cfg.map_path}: scan first"
        ) from None
    except (ValueError, KeyError) as e:
        raise WorkflowError(f"{cfg.map_path}: {e}") from None
    if tree_map.led_count != cfg.led_count:
        raise WorkflowError(
            f"the tree map has {tree_map.led_count} LEDs but the tree has {cfg.led_count}; "
            "scan again"
        )
    return tree_map


def set_interpolate(cfg: Config, index: int, interpolate: bool) -> None:
    """Make reconstruct ignore LED ``index``'s detections (or use them again)."""
    from treemap.scan.free import load_overrides, save_overrides

    _check_index(cfg, index)
    overrides = load_overrides(cfg.scan_dir)
    if interpolate:
        overrides.add(index)
    else:
        overrides.discard(index)
    save_overrides(cfg.scan_dir, overrides)


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
        # JSON has no NaN: a status with no LEDs gets null statistics
        "rows": [{"status": name, **{k: (None if isinstance(v, float) and v != v else v)
                                     for k, v in s.items()}}
                 for name, s in ev.table()],
    }


def compare_sim(cfg: Config) -> dict:
    """The map moved onto the simulated tree, for the viewer's Compare view: per LED the
    aligned position (metres, like the truth) and its error, plus the summary table."""
    import numpy as np

    ev = evaluate_sim(cfg)
    finite = np.isfinite(ev.aligned_m).all(axis=1)
    return {
        **evaluation_summary(ev),
        "positions": [[round(float(c), 5) for c in p] if ok else None
                      for p, ok in zip(ev.aligned_m, finite)],
        "errors_m": [round(float(e * ev.height_m), 5) if np.isfinite(e) else None
                     for e in ev.errors],
        "status": ev.status.tolist(),
    }


def _check_index(cfg: Config, index: int) -> None:
    if not 0 <= index < cfg.led_count:
        raise WorkflowError(f"LED index must be 0-{cfg.led_count - 1}, got {index}")
