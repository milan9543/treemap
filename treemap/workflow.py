"""The mapping workflow (scan, solve again, ignore an LED's readings) as plain
functions, which ``treemap serve`` runs as background jobs (:mod:`treemap.jobs`)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from treemap.config import Config

if TYPE_CHECKING:
    from treemap.cameras.base import Camera
    from treemap.mapping.model import TreeMap
    from treemap.outputs.base import LedOutput
    from treemap.scan.colours import ColourModel
    from treemap.scan.free import ScanSettings
    from treemap.scan.sfm import SfmResult


class WorkflowError(RuntimeError):
    """A step can't run; the message says why and what to do."""


# Waits until the phone's page has set its camera's exposure for the LEDs (calling
# check_cancel meanwhile); returns {"message": what was done, "settings": the camera's}.
CameraReady = Callable[[Callable[[], None]], dict]


def camera_colours(cfg: Config, camera_id: str) -> tuple[ColourModel | None, str | None]:
    """The colours measured for the phone ``camera_id`` at an earlier scan, and if there
    aren't any usable, why: ``(None, message)``."""
    from treemap.scan.colours import ColourError, ColourModel

    path = cfg.colours_path_for(camera_id)
    if not path.exists():
        return None, "this camera's colours haven't been measured, so colours may be misread"
    try:
        model = ColourModel.load(path)
    except ColourError as e:
        return None, f"ignoring the measured colours: {e}"
    if model.meta.get("camera") != camera_id:
        return None, f"the measured colours are for another camera ({model.meta.get('camera')})"
    measured_at = model.meta.get("brightness")
    if measured_at not in (None, cfg.scan.brightness):
        return model, (f"the colours were measured at brightness {measured_at}, the scan "
                       f"flashes at {cfg.scan.brightness}; if colours misread, scan again")
    return model, None


def scan_settings(cfg: Config, colours: ColourModel | None = None) -> ScanSettings:
    from treemap.scan.free import ScanSettings

    s = cfg.scan
    return ScanSettings(
        led_count=cfg.led_count, scan_dir=cfg.scan_dir, map_path=cfg.map_path,
        symbol_s=s.symbol_ms / 1000, brightness=s.brightness, round_s=s.round_s,
        status_s=s.status_s, max_rounds=s.max_rounds, fov_deg=s.fov_deg,
        colours=colours, shape=cfg.shape,
    )


def run_scan(
    cfg: Config,
    output: LedOutput,
    camera: Camera,
    camera_id: str,
    *,
    rounds: int | None = None,
    fresh: bool = True,
    camera_ready: CameraReady | None = None,
    next_round: Callable[[int, Callable[[], None]], bool] | None = None,
    on_update: Callable[[dict], None] = lambda u: None,
    check_cancel: Callable[[], None] = lambda: None,
    on_message: Callable[[str], None] = lambda m: None,
) -> TreeMap | None:
    """Scan in rounds (see :mod:`treemap.scan.free`) with ``camera``, the phone named
    ``camera_id`` (for its measured colours). Earlier rounds are forgotten (unless not
    ``fresh``: then this scan adds to them, to scan parts again); the rounds of this scan
    build on each other.

    First the camera gets ready (:func:`prepare_camera`: a countdown, then the phone's
    exposure and colours). ``on_update`` gets progress dicts, ``round`` 0 while getting
    ready. Interrupting (any exception from a callback) keeps the rounds finished so far.
    ``next_round`` makes the status between rounds wait for the user (see
    :func:`treemap.scan.free.scan`).
    """
    from treemap.scan.free import ScanError, scan

    with camera:
        try:
            colours = prepare_camera(cfg, camera, camera_id, output, on_update, check_cancel,
                                     on_message, camera_ready)
            return scan(output, camera, scan_settings(cfg, colours), fresh=fresh, rounds=rounds,
                        on_update=on_update, check_cancel=check_cancel, next_round=next_round)
        except ScanError as e:
            raise WorkflowError(str(e)) from None


def prepare_camera(
    cfg: Config,
    camera: Camera,
    camera_id: str,
    output: LedOutput,
    on_update: Callable[[dict], None] = lambda u: None,
    check_cancel: Callable[[], None] = lambda: None,
    on_message: Callable[[str], None] = lambda m: None,
    camera_ready: CameraReady | None = None,
) -> ColourModel | None:
    """Get the camera ready to scan; returns the colours to read the code by.

    1. **countdown** (``scan.countdown_s``): the LEDs glow dim white, to point the
       camera at them.
    2. **exposure**: the phone's page sets its camera's exposure and white balance for
       the LEDs, which ``camera_ready`` waits for, while the LEDs show the code's colours
       (:func:`treemap.cameras.check.mixed`, so the dimmest colour counts).
    3. **colours**: how the camera sees each colour of the code at that exposure is
       measured and saved. If too few LEDs were seen, the last measurement is used.

    Without ``camera_ready``, 2 and 3 are skipped and the last measurement is used.
    """
    import time

    from treemap.cameras.check import SYNC, mixed, solid

    brightness = cfg.scan.brightness
    glow = solid(output.led_count, SYNC, max(brightness // 4, 8))
    end = time.monotonic() + cfg.scan.countdown_s
    while (left := end - time.monotonic()) > 0:
        check_cancel()
        output.show(glow)
        on_update({"round": 0, "phase": "countdown", "remaining": round(left, 1)})
        time.sleep(min(0.25, left))

    if camera_ready is None:
        colours, problem = camera_colours(cfg, camera_id)
        if problem:
            on_message(problem)
        return colours
    on_update({"round": 0, "phase": "exposure"})
    output.show(mixed(output.led_count, brightness))
    ready = camera_ready(check_cancel)
    if ready.get("message"):
        on_message(ready["message"])
    return _measure_colours(cfg, camera, output, on_update, check_cancel, on_message,
                            camera_id, ready.get("settings") or {}, settle_s=1.0,
                            exposure=ready.get("message"))


def _measure_colours(
    cfg: Config, camera: Camera, output: LedOutput, on_update: Callable[[dict], None],
    check_cancel: Callable[[], None], on_message: Callable[[str], None],
    camera_id: str, settings: dict, settle_s: float = 0.6, exposure: str | None = None,
) -> ColourModel | None:
    """Step 3 of :func:`prepare_camera`. The page's frames arrive in batches up to half
    a second late, hence its longer ``settle_s``."""
    from treemap.cameras.check import COLOURS, advice, colour_check

    sample_s = 1.5
    brightness = cfg.scan.brightness

    def on_colour(i: int) -> None:
        check_cancel()
        on_update({"round": 0, "phase": "colours",
                   "remaining": round((len(COLOURS) - i) * (settle_s + sample_s), 1)})

    results, model = colour_check(camera, output, brightness, settle_s, sample_s, on_colour)
    check_cancel()
    seen = model is not None and min(r.blobs for r in results) >= 10
    tips = advice(results, model, brightness)
    on_update({"round": 0, "phase": "colours", "remaining": 0, "colours": {
        "ok": seen and not tips,
        "read_right": {r.name: None if r.share != r.share else round(r.share, 3)
                       for r in results},
        "seen": {r.name: r.blobs for r in results},
        "tips": tips,
    }})
    if seen:
        save_colours(cfg, model, results, camera_id, settings, exposure)
        on_message("colours read right: " + ", ".join(f"{r.name} {r.share:.0%}" for r in results))
        return model
    on_message("too few LEDs seen to measure the colours; point the camera at the LEDs")
    colours, problem = camera_colours(cfg, camera_id)
    if problem:
        on_message(problem)
    return colours


def save_colours(cfg: Config, model: ColourModel, results: list, camera_id: str,
                 settings: dict | None = None, exposure: str | None = None) -> Path:
    """Save measured colours for ``camera_id``, with the camera settings they were
    measured at (and how the exposure was found, if the page said). Returns where."""
    size = next((r.sample.shape[1::-1] for r in results if r.sample is not None), None)
    model.meta.update(camera=camera_id, video_size=list(size) if size else None,
                      camera_settings=settings or {},
                      read_right={r.name: None if r.share != r.share else round(r.share, 3)
                                  for r in results})
    if exposure:
        model.meta["exposure"] = exposure
    path = cfg.colours_path_for(camera_id)
    model.save(path)
    return path


def rebuild_map(cfg: Config) -> tuple[TreeMap, SfmResult]:
    """Solve again from the saved rounds (honouring ``fix`` overrides) and save the map,
    facing the way the map it replaces was set to face."""
    from treemap.mapping.model import TreeMap
    from treemap.scan.free import ScanError, build_map, load_overrides, load_rounds
    from treemap.scan.sfm import SfmError

    try:
        before = TreeMap.load(cfg.map_path)  # keeps the way it was set to face
    except (OSError, ValueError, KeyError, TypeError):
        before = None
    try:
        tree_map, res = build_map(load_rounds(cfg.scan_dir), cfg.led_count,
                                  load_overrides(cfg.scan_dir), cfg.shape, before)
    except (ScanError, SfmError) as e:
        raise WorkflowError(f"can't reconstruct from {cfg.scan_dir}: {e}") from None
    tree_map.save(cfg.map_path)
    return tree_map, res


def rounds_shape(cfg: Config) -> str | None:
    """The shape the saved rounds were scanned as (that of the map they made), if any."""
    from treemap.mapping.model import TreeMap

    try:
        return TreeMap.load(cfg.map_path).shape
    except (OSError, ValueError, KeyError, TypeError):
        return None


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


def _check_index(cfg: Config, index: int) -> None:
    if not 0 <= index < cfg.led_count:
        raise WorkflowError(f"LED index must be 0-{cfg.led_count - 1}, got {index}")
