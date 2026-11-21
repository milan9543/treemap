"""The mapping workflow (scan, reconstruct, fix, evaluate) as plain functions.

Both the command line and the viewer's server drive the same steps through here; they
differ only in how they report progress.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from treemap.config import Config, parse_leds

if TYPE_CHECKING:
    from treemap.cameras.base import Camera
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


def camera_colours(cfg: Config, camera_id: str | None = None) -> tuple[ColourModel | None, str | None]:
    """The measured colours (from ``treemap camera check``) of the configured camera, or
    of ``camera_id``, and if there aren't any usable, why: ``(None, message)``. The sim
    camera's colours are pure enough not to need them."""
    from treemap.scan.colours import ColourError, ColourModel

    camera_id = camera_id or cfg.camera_id
    path = cfg.colours_path
    if not path.exists():
        return None, (None if camera_id == "sim" else
                      "this camera's colours haven't been measured, so colours may be misread")
    try:
        model = ColourModel.load(path)
    except ColourError as e:
        return None, f"ignoring the measured colours: {e}"
    if model.meta.get("camera") != camera_id:
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
        colours=colours, shape=cfg.shape,
    )


def run_scan(
    cfg: Config,
    output: LedOutput,
    *,
    rounds: int | None = None,
    sim_port: int | None = None,
    camera: Camera | None = None,
    camera_id: str | None = None,
    on_update: Callable[[dict], None] = lambda u: None,
    check_cancel: Callable[[], None] = lambda: None,
    on_message: Callable[[str], None] = lambda m: None,
) -> TreeMap | None:
    """Scan from scratch, in rounds (see :mod:`treemap.scan.free`), with the configured
    camera, or ``camera`` (named ``camera_id`` for its measured colours). Earlier rounds
    are forgotten; the rounds of this scan build on each other.

    First the camera gets ready (:func:`prepare_camera`: a countdown, then the Android
    camera's exposure and colours). ``on_update`` gets progress dicts, ``round`` 0 while
    getting ready. Interrupting (any exception from a callback) keeps the rounds
    finished so far.
    """
    from treemap.cameras import CameraError, create_camera
    from treemap.cameras.browser import CameraUnavailable
    from treemap.scan.free import ScanError, scan

    if camera is None:
        try:
            camera = create_camera(cfg, sim_port)
        except (CameraError, NotImplementedError) as e:
            raise WorkflowError(str(e)) from None
    with camera:
        try:
            colours = prepare_camera(cfg, camera, output, on_update, check_cancel, on_message,
                                     camera_id)
            return scan(output, camera, scan_settings(cfg, colours), fresh=True, rounds=rounds,
                        on_update=on_update, check_cancel=check_cancel)
        except (ScanError, CameraUnavailable) as e:
            raise WorkflowError(str(e)) from None


def prepare_camera(
    cfg: Config,
    camera: Camera,
    output: LedOutput,
    on_update: Callable[[dict], None] = lambda u: None,
    check_cancel: Callable[[], None] = lambda: None,
    on_message: Callable[[str], None] = lambda m: None,
    camera_id: str | None = None,
) -> ColourModel | None:
    """Get the camera ready to scan; returns the colours to read the code by.

    1. **countdown** (``scan.countdown_s``): the LEDs glow dim white, to point the
       camera at them.
    2. **exposure**: a camera that can (the Android one) gets its exposure and white
       balance set for the LEDs (:func:`treemap.cameras.check.fix_exposure`).
    3. **colours**: how it sees each colour of the code at that exposure is measured
       and saved, as ``treemap camera check`` does. If too few LEDs were seen, the last
       measurement is used.
    """
    import time

    from treemap.cameras.check import SYNC, colour_check, fix_exposure, solid

    brightness = cfg.scan.brightness
    glow = solid(output.led_count, SYNC, max(brightness // 4, 8))
    end = time.monotonic() + cfg.scan.countdown_s
    while (left := end - time.monotonic()) > 0:
        check_cancel()
        output.show(glow)
        on_update({"round": 0, "phase": "countdown", "remaining": round(left, 1)})
        time.sleep(min(0.25, left))
    if not hasattr(camera, "exposure"):  # the sim camera or the phone's page: nothing to set
        colours, problem = camera_colours(cfg, camera_id)
        if problem:
            on_message(problem)
        return colours

    on_update({"round": 0, "phase": "exposure"})
    if (done := fix_exposure(camera, output, brightness)) is not None:
        on_message(done)
    check_cancel()
    on_update({"round": 0, "phase": "colours"})
    results, model = colour_check(camera, output, brightness)
    check_cancel()
    if model is not None and min(r.blobs for r in results) >= 10:
        save_colours(cfg, model, camera, results)
        on_message("colours read right: " + ", ".join(f"{r.name} {r.share:.0%}" for r in results))
        return model
    on_message("too few LEDs seen to measure the colours; point the camera at the LEDs")
    colours, problem = camera_colours(cfg, camera_id)
    if problem:
        on_message(problem)
    return colours


def save_colours(cfg: Config, model: ColourModel, camera: Camera, results: list) -> None:
    """Save measured colours for the configured camera, with the settings they need."""
    size = next((r.sample.shape[1::-1] for r in results if r.sample is not None), None)
    model.meta.update(camera=cfg.camera_id, video_size=list(size) if size else None,
                      camera_settings=camera.exposure()["settings"]
                      if hasattr(camera, "exposure") else {})
    model.save(cfg.colours_path)


def rebuild_map(cfg: Config) -> tuple[TreeMap, SfmResult]:
    """Solve again from the saved rounds (honouring ``fix`` overrides) and save the map."""
    from treemap.scan.free import ScanError, build_map, load_overrides, load_rounds
    from treemap.scan.sfm import SfmError

    try:
        tree_map, res = build_map(load_rounds(cfg.scan_dir), cfg.led_count,
                                  load_overrides(cfg.scan_dir), cfg.shape)
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
