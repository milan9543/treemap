"""The ``treemap`` command line."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import webbrowser
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated

import numpy as np
import typer
import yaml

from treemap import __version__
from treemap.config import CONFIG_ENV_VAR, Config, ConfigError, load_config

app = typer.Typer(
    help="Map the 3D positions of WLED Christmas tree LEDs and run position-aware effects.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Inspect the configuration.", no_args_is_help=True)
sim_app = typer.Typer(help="Simulated tree and 3D viewer.", no_args_is_help=True)
test_app = typer.Typer(
    help="Test patterns for checking wiring and index order.", no_args_is_help=True
)
app.add_typer(config_app, name="config")
app.add_typer(sim_app, name="sim")
app.add_typer(test_app, name="test")


@dataclass
class State:
    """Per-invocation state. The config is loaded lazily so ``--help`` never needs it."""

    config_path: Path | None
    _config: Config | None = None

    @property
    def config(self) -> Config:
        if self._config is None:
            try:
                self._config = load_config(self.config_path)
            except ConfigError as e:
                fail(f"Config error: {e}", code=2)
        return self._config


def fail(message: str, code: int = 1) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=code)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"treemap {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            envvar=CONFIG_ENV_VAR,
            help="Config file. Defaults to ./config.yaml, or built-in defaults if absent.",
            show_default=False,
        ),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Log more detail.")] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show the version."
        ),
    ] = False,
) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s: %(message)s"
    )
    if not verbose:
        logging.getLogger("websockets").setLevel(logging.ERROR)
    ctx.obj = State(config_path=config)


# -- config ---------------------------------------------------------------------------


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    """Validate the config and print the effective values (file merged with defaults)."""
    cfg = ctx.obj.config
    source = cfg.source if cfg.source else "built-in defaults (no config.yaml found)"
    typer.secho(f"# source: {source}", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(yaml.safe_dump(cfg.to_dict(), sort_keys=False).rstrip())


# -- sim ------------------------------------------------------------------------------


def _new_tree(cfg: Config, spec=None):
    from treemap.sim.tree import generate_tree, spec_from_config

    tree = generate_tree(spec or spec_from_config(cfg))
    tree.save(cfg.sim_tree_path)
    return tree


def _describe_tree(tree, led_count: int | None = None) -> str:
    lines = [
        f"seed {tree.seed}: {tree.led_count} LEDs on {len(tree.strands)} strip(s), "
        f"{tree.layout}, height {tree.height:.2f} m, radius {tree.radius:.2f} m"
    ]
    for i, s in enumerate(tree.strands, 1):
        quirk = ", index 0 at the TOP" if s.index_from_top else ""
        lines.append(
            f"  strip {i}: LEDs {s.start}-{s.start + s.count - 1}, "
            f"{s.count * s.spacing:.1f} m ({s.spacing * 100:.1f} cm spacing), "
            f"{s.turns:.1f} turns {s.handedness}{quirk}"
        )
    lines += [typer.style(f"  warning: {w}", fg=typer.colors.YELLOW) for w in tree.warnings]
    if led_count is not None and led_count != tree.led_count:
        lines.append(
            typer.style(
                f"  warning: the tree has {tree.led_count} LEDs but led_count in the config "
                f"is {led_count}; test patterns and effects will drive {led_count}.",
                fg=typer.colors.YELLOW,
            )
        )
    return "\n".join(lines)


def _parse_strip(text: str):
    """``LEDS[:LENGTH][:START]``, e.g. ``200``, ``200:14``, ``150:12:top``."""
    from treemap.sim.tree import STARTS, StripSpec

    parts = text.split(":")
    try:
        strip = StripSpec(leds=int(parts[0]))
        for p in parts[1:]:
            if p in STARTS:
                strip.start = p
            elif p:
                strip.length = float(p)
    except ValueError:
        raise typer.BadParameter(
            f"{text!r}: expected LEDS[:LENGTH][:START], e.g. 200, 200:14 or 200:14:top",
            param_hint="--strip",
        ) from None
    return strip


@sim_app.command("new")
def sim_new(
    ctx: typer.Context,
    seed: Annotated[
        int | None, typer.Option(help="Random seed. Default: sim.seed, else random.")
    ] = None,
    strip: Annotated[
        list[str] | None,
        typer.Option(
            "--strip",
            help="A strip as LEDS[:LENGTH_M][:bottom|top|auto]; repeat for each strip. "
            "Default: sim.strips.",
            show_default=False,
        ),
    ] = None,
    height: Annotated[float | None, typer.Option(help="Tree height in metres.")] = None,
    radius: Annotated[float | None, typer.Option(help="Base radius in metres.")] = None,
    layout: Annotated[
        str | None, typer.Option(help="interleaved, stacked or auto.", show_default=False)
    ] = None,
    quirks: Annotated[
        bool | None,
        typer.Option(
            "--quirks/--no-quirks",
            help="Let 'auto' settings pick wiring quirks at random. Default: sim.quirks.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Generate a tree and save it as the simulator's ground truth.

    Defaults come from the `sim` section of the config; options override them.
    """
    from treemap.sim.tree import SpecError, spec_from_config

    cfg = ctx.obj.config
    spec = spec_from_config(cfg)
    if strip:
        spec.strips = [_parse_strip(s) for s in strip]
    for name, value in (("seed", seed), ("height", height), ("radius", radius),
                        ("layout", layout), ("quirks", quirks)):
        if value is not None:
            setattr(spec, name, value)
    try:
        tree = _new_tree(cfg, spec)
    except SpecError as e:
        fail(str(e), code=2)
    typer.echo(_describe_tree(tree, cfg.led_count))
    typer.secho(f"saved {cfg.sim_tree_path}", fg=typer.colors.GREEN)


@sim_app.command("view")
def sim_view(
    ctx: typer.Context,
    browser: Annotated[bool, typer.Option(help="Open the viewer in a browser.")] = True,
    port: Annotated[int | None, typer.Option(help="Port. Default: sim.port.")] = None,
) -> None:
    """Serve the 3D viewer. Leave it running; other commands stream colours to it."""
    from treemap.sim.server import SimServer
    from treemap.sim.tree import SimTree, spec_from_config

    cfg = ctx.obj.config
    if not cfg.sim_tree_path.exists():
        typer.echo("No simulated tree yet, generating one:")
        typer.echo(_describe_tree(_new_tree(cfg), cfg.led_count))
    else:
        try:
            SimTree.load(cfg.sim_tree_path)
        except (ValueError, KeyError, TypeError) as e:
            typer.echo(f"Existing tree can't be used ({e}); generating a new one:")
            typer.echo(_describe_tree(_new_tree(cfg), cfg.led_count))

    server = SimServer(
        tree_path=cfg.sim_tree_path,
        map_path=cfg.map_path,
        host=cfg.sim.host,
        port=port or cfg.sim.port,
        led_count=cfg.led_count,
        defaults=spec_from_config(cfg),
        make_engine=lambda s: _make_engine(cfg, sim_port=s.port, source="viewer: effects"),
        output_label=_output_label(cfg),
        cfg=cfg,
        make_jobs=lambda s: _make_jobs(cfg, s),
    )

    def ready(s: SimServer) -> None:
        typer.secho(f"Viewer running at {s.url}  (Ctrl-C to stop)", fg=typer.colors.GREEN)
        if browser:
            webbrowser.open(s.url)

    try:
        asyncio.run(server.serve(on_ready=ready))
    except KeyboardInterrupt:
        typer.echo("\nstopped")
    except OSError as e:
        fail(f"Can't start the viewer on {cfg.sim.host}:{server.port}: {e.strerror or e}")


@sim_app.command("evaluate")
def sim_evaluate(ctx: typer.Context) -> None:
    """Compare the reconstructed map with the simulated tree's true positions.

    Errors are measured after the best rotation, scale and offset, as a percentage of
    the tree's LED height (and in cm).
    """
    from treemap import workflow

    cfg = ctx.obj.config
    try:
        ev = workflow.evaluate_sim(cfg)
    except workflow.WorkflowError as e:
        fail(str(e))
    h = ev.height_m * 100
    typer.echo(f"tree LEDs span {ev.height_m:.2f} m; alignment: rotated {ev.rotation_deg:+.1f}°, "
               f"scale {ev.scale:.3f}")
    typer.echo(f"  {'':<13}{'LEDs':>5}  {'median':>15}  {'p95':>15}")
    for name, s in ev.table():
        if s["count"]:
            typer.echo(
                f"  {name:<13}{s['count']:>5}  {s['median'] * 100:>5.2f}% {s['median'] * h:>5.1f} cm"
                f"   {s['p95'] * 100:>5.2f}% {s['p95'] * h:>5.1f} cm"
            )
        else:
            typer.echo(f"  {name:<13}{0:>5}")


# -- effects --------------------------------------------------------------------------

class MapChoice(str, Enum):
    scanned = "scanned"
    truth = "truth"


SecondsOptRun = Annotated[
    float | None,
    typer.Option(help="How long to run. Default: until Ctrl-C.", show_default=False),
]


def _output_label(cfg: Config) -> str:
    if cfg.output == "wled":
        return "wled: " + ", ".join(c.host for c in cfg.controllers)
    return "sim"


def _output_factory(cfg: Config, sim_port: int | None = None, source: str | None = None):
    """Opens the configured output (the sim viewer on ``sim_port``). ``source`` names
    the sender in the viewer (default: this command)."""
    from treemap.outputs import create_output
    from treemap.outputs.sim import SimOutput

    def factory():
        if cfg.output == "sim":
            return SimOutput(cfg.led_count, host=cfg.sim.host, port=sim_port or cfg.sim.port,
                             source=source)
        return create_output(cfg)

    return factory


def _make_jobs(cfg: Config, server):
    """Background scan/reconstruct/fix jobs for the viewer served by ``server``."""
    from treemap.jobs import Jobs

    def stop_effects() -> None:
        if server.engine is not None:
            server.engine.stop()

    return Jobs(cfg, _output_factory(cfg, server.port, source="viewer: scan"),
                stop_effects=stop_effects, sim_port=server.port)


def _make_engine(cfg: Config, sim_port: int | None = None, brightness: float | None = None,
                 fps: float | None = None, source: str | None = None, map_choice: str = "scanned"):
    """An effects engine sending to the configured output (the sim viewer on ``sim_port``).
    3D effects use the scanned map, or with ``map_choice="truth"`` the simulated tree."""
    from treemap.effects import EffectContext
    from treemap.engine import Engine
    from treemap.mapping.source import MapSource

    fps = fps or cfg.engine.fps
    truth = cfg.sim_tree_path if cfg.output == "sim" or map_choice == "truth" else None
    return Engine(
        _output_factory(cfg, sim_port, source),
        EffectContext(n=cfg.led_count, fps=fps,
                      tree_map=MapSource(cfg.map_path, truth, map_choice)),
        fps=fps,
        brightness=cfg.engine.brightness if brightness is None else brightness,
        crossfade_s=cfg.engine.crossfade,
        gamma=cfg.gamma,
    )


@app.command("effects")
def effects_list(ctx: typer.Context) -> None:
    """List the effects and their parameters."""
    from treemap.effects import describe_effects

    group = None
    for e in describe_effects(ctx.obj.config.led_count):
        if e["group"] != group:
            group = e["group"]
            typer.secho(f"\n{group}", bold=True)
        typer.secho(f"  {e['name']:<11}", fg=typer.colors.GREEN, nl=False)
        typer.echo(e["description"])
        for p in e["params"]:
            rng = f" {p['min']:g} to {p['max']:g}" if p["min"] is not None else ""
            choices = f" {'|'.join(p['choices'])}" if p["choices"] else ""
            typer.secho(
                f"      {p['name']}={p['default']}  ({p['kind']}{rng}{choices})"
                + (f" {p['help']}" if p["help"] else ""),
                fg=typer.colors.BRIGHT_BLACK,
            )


@app.command("run")
def run_effect(
    ctx: typer.Context,
    effect: Annotated[str, typer.Argument(help="Effect name; see `treemap effects`.")],
    param: Annotated[
        list[str] | None,
        typer.Option("--param", "-p", help="Effect parameter as key=value; repeatable."),
    ] = None,
    seconds: SecondsOptRun = None,
    brightness: Annotated[
        float | None, typer.Option(min=0, max=1, help="0-1. Default: engine.brightness.")
    ] = None,
    fps: Annotated[float | None, typer.Option(min=1, max=120, help="Default: engine.fps.")] = None,
    map_choice: Annotated[
        MapChoice, typer.Option("--map", help="Positions for the 3D effects: the scanned map, "
                                "or the simulated tree's true ones.")
    ] = MapChoice.scanned,
) -> None:
    """Run an effect on the configured output until Ctrl-C."""
    import time

    from treemap.effects import ParamError

    cfg = ctx.obj.config
    params = {}
    for item in param or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise typer.BadParameter(f"{item!r}: expected key=value", param_hint="--param")
        params[key.strip()] = value.strip()

    engine = _make_engine(cfg, brightness=brightness, fps=fps, map_choice=map_choice.value)
    try:
        engine.start(effect, params)
    except KeyError as e:
        fail(e.args[0], code=2)
    except ParamError as e:
        fail(str(e), code=2)
    typer.echo(f"running {effect} at {engine.fps:g} fps"
               f"{f' for {seconds:g} s' if seconds else ' (Ctrl-C to stop)'}")
    try:
        end = None if seconds is None else time.monotonic() + seconds
        while engine.running and (end is None or time.monotonic() < end):
            engine.wait(0.1)
    except KeyboardInterrupt:
        typer.echo("\nstopped")
    finally:
        engine.stop()
    if engine.error:
        fail(engine.error)


# -- scan -----------------------------------------------------------------------------


@app.command("scan")
def scan(
    ctx: typer.Context,
    rounds: Annotated[
        int | None,
        typer.Option(min=1, help="Rounds to run. Default: scan.max_rounds (it also stops "
                     "once every LED is ok).", show_default=False),
    ] = None,
    fresh: Annotated[
        bool, typer.Option(help="Forget earlier rounds and start over.")
    ] = False,
) -> None:
    """Flash every LED's code while you walk round the tree with the camera.

    Each round flashes for scan.round_s seconds, solves the positions from every round so
    far, then shows the result on the tree for scan.status_s: green ok, yellow
    interpolated, red failed. Walk to the red parts for the next round. With the sim
    camera, walk round the tree in the viewer (`treemap sim view`, press f).
    """
    from treemap import workflow

    cfg = ctx.obj.config
    if workflow.ensure_sim_tree(cfg):
        typer.echo("No simulated tree yet, generated one.")
    with _output(ctx) as out:
        try:
            tree_map = workflow.run_scan(cfg, out, fresh=fresh, rounds=rounds,
                                         on_update=_scan_progress)
        except workflow.WorkflowError as e:
            typer.echo()
            fail(str(e))
    typer.echo()
    if tree_map is None:
        fail("no map yet: too few LEDs were identified (is the camera on the tree?)")
    _map_summary(tree_map)
    typer.secho(f"saved {cfg.map_path}", fg=typer.colors.GREEN)


def _scan_progress(u: dict) -> None:
    phase = u["phase"]
    if phase == "flashing":
        typer.echo(f"\rround {u['round']}: flashing, {u['remaining']:4.1f} s left, "
                   f"{u['identified']} LEDs identified   ", nl=False)
    elif phase == "solving":
        typer.echo(f"\rround {u['round']}: {u['identified']} LEDs identified in "
                   f"{u['frames']} frames; solving…" + " " * 12, nl=False)
    elif phase == "status":
        c = u.get("counts")
        result = (f"{c['ok']} ok, {c['interpolated']} interpolated, {c['failed']} failed"
                  if c else u.get("message") or "no map yet")
        typer.echo(f"\rround {u['round']}: {result}" + " " * 20)


def _ranges(indices: list[int], limit: int = 30) -> str:
    """``[1, 2, 3, 7, 9, 10]`` -> ``1-3, 7, 9-10``."""
    parts: list[str] = []
    for i in indices:
        if parts and i == last + 1:
            parts[-1] = f"{parts[-1].split('-')[0]}-{i}"
        else:
            parts.append(str(i))
        last = i
    more = f", … ({len(parts) - limit} more)" if len(parts) > limit else ""
    return ", ".join(parts[:limit]) + more


def _rebuild_map(cfg: Config):
    """Solve from the saved rounds (honouring overrides) and save the map."""
    from treemap import workflow

    try:
        return workflow.rebuild_map(cfg)[0]
    except workflow.WorkflowError as e:
        fail(f"Can't reconstruct: {e}")


def _map_summary(tree_map) -> None:
    c = tree_map.counts()
    labels = {"ok": ("green", typer.colors.GREEN), "interpolated": ("yellow", typer.colors.YELLOW),
              "failed": ("red", typer.colors.RED)}
    for status, (colour, fg) in labels.items():
        typer.secho(f"  {status:<13}{c[status]:>4}  {colour}", fg=fg, nl=False)
        idx = tree_map.indices(status) if status != "ok" else []
        typer.echo(f": {_ranges(idx)}" if idx else "")
    if tree_map.meta.get("outliers"):
        typer.echo(f"  dropped as outliers: {_ranges(tree_map.meta['outliers'])}")
    if tree_map.meta.get("forced_interpolate"):
        typer.echo(f"  interpolated by `fix`: {_ranges(tree_map.meta['forced_interpolate'])}")


@app.command("reconstruct")
def reconstruct_cmd(ctx: typer.Context) -> None:
    """Solve the LED positions again from the saved scan rounds and write the tree map."""
    cfg = ctx.obj.config
    tree_map = _rebuild_map(cfg)
    m = tree_map.meta
    typer.echo(f"{m.get('rounds')} round(s), {m.get('registered')} camera views; reprojection "
               f"error median {m.get('median_residual_px')} px, focal length "
               f"{m.get('focal_px')} px")
    _map_summary(tree_map)
    typer.secho(f"saved {cfg.map_path}", fg=typer.colors.GREEN)


def _load_map(cfg: Config):
    from treemap import workflow

    try:
        return workflow.load_map(cfg)
    except workflow.WorkflowError as e:
        fail(f"{e} (`treemap scan`)")


@app.command("show-mapping")
def show_mapping(
    ctx: typer.Context,
    verify: Annotated[
        bool,
        typer.Option(
            "--verify",
            help="Sweep a rising plane, then a left-to-right one, through the mapped "
            "positions. An LED lighting out of step with its neighbours is mis-mapped.",
        ),
    ] = False,
    seconds: SecondsOpt = None,
    sweep: Annotated[float, typer.Option(min=1, help="Seconds per sweep with --verify.")] = 6.0,
    loop: Annotated[bool, typer.Option(help="With --verify: repeat until Ctrl-C.")] = False,
) -> None:
    """Light each LED by mapping quality: green ok, yellow interpolated, red failed."""
    from treemap.mapping.quality import status_frame, verify_frames
    from treemap.patterns import hold, play

    cfg = ctx.obj.config
    tree_map = _load_map(cfg)
    typer.echo(f"{cfg.map_path} ({tree_map.meta.get('created', '?')}):")
    _map_summary(tree_map)
    problems = tree_map.indices("interpolated") + tree_map.indices("failed")
    if problems:
        typer.echo(f"inspect one with: treemap fix {problems[0]}")
    with _output(ctx) as out:
        if verify:
            typer.echo("rising plane, then left-to-right sweep"
                       + (" (Ctrl-C to stop)" if loop else ""))
            while True:
                play(out, verify_frames(tree_map, fps=cfg.engine.fps, seconds=sweep),
                     cfg.engine.fps)
                if not loop:
                    break
        else:
            typer.echo(f"showing status colours{'' if seconds else ' (Ctrl-C to stop)'}")
            hold(out, status_frame(tree_map), seconds)


@app.command("fix")
def fix(
    ctx: typer.Context,
    index: Annotated[int, typer.Argument(min=0, help="LED to inspect.")],
    action: Annotated[
        str | None,
        typer.Option(help="interpolate, measure or keep. Default: ask.", show_default=False),
    ] = None,
) -> None:
    """Show one LED blue (neighbours dim), then interpolate it or measure it again.

    `interpolate` ignores its observations from now on and fills it in from its
    neighbours (for an LED the camera keeps misreading); `measure` undoes that. To
    measure a hidden LED better, run `treemap scan` again and film that part of the tree.
    """
    from treemap import workflow
    from treemap.mapping.quality import fix_frame
    from treemap.patterns import showing

    cfg = ctx.obj.config
    n = cfg.led_count
    if index >= n:
        raise typer.BadParameter(f"must be below led_count ({n})", param_hint="INDEX")
    choices = ("interpolate", "measure", "keep")
    if action not in (None, *choices):
        raise typer.BadParameter(", ".join(choices), param_hint="--action")
    tree_map = _load_map(cfg)
    _describe_led(tree_map, index)

    with _output(ctx) as out:
        with showing(out, fix_frame(n, index)):
            typer.echo(f"LED {index} is lit blue, its neighbours dim white.")
            while action not in choices:
                answer = typer.prompt("[i]nterpolate, [m]easure again or [k]eep?", default="k")
                action = {"i": "interpolate", "m": "measure", "k": "keep"}.get(
                    answer.strip().lower()[:1]
                )
    if action == "keep":
        return
    try:
        workflow.set_interpolate(cfg, index, action == "interpolate")
    except workflow.WorkflowError as e:
        fail(str(e))
    tree_map = _rebuild_map(cfg)
    typer.echo(f"map rebuilt; LED {index} is now {tree_map.status[index]}")


def _describe_led(tree_map, index: int) -> None:
    status = tree_map.status[index]
    fg = {"ok": typer.colors.GREEN, "interpolated": typer.colors.YELLOW}.get(status, typer.colors.RED)
    typer.secho(f"LED {index}: {status}", fg=fg, bold=True)
    views = tree_map.meta.get("views")
    if views and index < len(views):
        typer.echo(f"  seen well in {views[index]} camera views")
    if index in tree_map.meta.get("outliers", []):
        typer.echo("  dropped as an outlier: too far from its neighbours on the strip")
    if index in tree_map.meta.get("forced_interpolate", []):
        typer.echo("  interpolated on request (treemap fix)")
    lo, hi = max(index - 3, 0), min(index + 4, tree_map.led_count)
    near = ", ".join(f"{j} {tree_map.status[j]}" for j in range(lo, hi) if j != index)
    typer.echo(f"  neighbours: {near}")


# -- test patterns --------------------------------------------------------------------


@contextlib.contextmanager
def _output(ctx: typer.Context, off_on_exit: bool = True) -> Iterator:
    """Open the configured output; turn LEDs off and close it on exit or Ctrl-C."""
    from treemap.outputs import create_output

    cfg = ctx.obj.config
    try:
        out = create_output(cfg)
    except NotImplementedError as e:
        fail(str(e))
    interrupted = False
    try:
        yield out
    except KeyboardInterrupt:
        interrupted = True
    finally:
        try:
            if off_on_exit or interrupted:
                out.off()
        finally:
            out.close()
    if interrupted:
        typer.echo("\nstopped")


def _color(value: str) -> tuple[int, int, int]:
    from treemap.patterns import parse_color

    try:
        return parse_color(value)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from None


ColorOpt = Annotated[
    str, typer.Option("--color", help="Colour name, #rrggbb or r,g,b.", show_default=True)
]
SecondsOpt = Annotated[
    float | None,
    typer.Option(help="How long to keep it lit. Default: until Ctrl-C.", show_default=False),
]


@test_app.command("chase")
def test_chase(
    ctx: typer.Context,
    fps: Annotated[float, typer.Option(min=0.5, max=200, help="LEDs per second.")] = 20.0,
    color: ColorOpt = "white",
    width: Annotated[int, typer.Option(min=1, help="Lit LEDs, fading behind the head.")] = 3,
    loop: Annotated[bool, typer.Option(help="Repeat until Ctrl-C.")] = False,
) -> None:
    """Run a light along the LEDs from index 0 to the last one."""
    from treemap.patterns import chase_frames, play

    rgb = _color(color)
    n = ctx.obj.config.led_count
    with _output(ctx) as out:
        while True:
            play(
                out,
                chase_frames(n, rgb, width),
                fps,
                on_frame=lambda i: typer.echo(f"\rLED {i:>4} / {n - 1}", nl=False),
            )
            typer.echo()
            if not loop:
                break


@test_app.command("led")
def test_led(
    ctx: typer.Context,
    index: Annotated[int, typer.Argument(min=0, help="Global LED index.")],
    color: ColorOpt = "white",
    seconds: SecondsOpt = None,
) -> None:
    """Light a single LED."""
    from treemap.patterns import hold, single

    n = ctx.obj.config.led_count
    if index >= n:
        raise typer.BadParameter(f"index must be below led_count ({n})", param_hint="INDEX")
    rgb = _color(color)
    with _output(ctx) as out:
        typer.echo(f"LED {index} lit{'' if seconds else ' (Ctrl-C to turn off)'}")
        hold(out, single(n, index, rgb), seconds)


@test_app.command("all-white")
def test_all_white(
    ctx: typer.Context,
    level: Annotated[
        int,
        typer.Option(
            min=1,
            max=255,
            help="Brightness 1-255. Full white on 400 LEDs can draw ~24 A: mind the PSU.",
        ),
    ] = 96,
    seconds: SecondsOpt = None,
) -> None:
    """Light every LED white."""
    from treemap.patterns import hold

    n = ctx.obj.config.led_count
    with _output(ctx) as out:
        typer.echo(f"all {n} LEDs white at {level}/255{'' if seconds else ' (Ctrl-C to stop)'}")
        hold(out, np.full((n, 3), level, dtype=np.uint8), seconds)


@test_app.command("off")
def test_off(ctx: typer.Context) -> None:
    """Turn every LED off."""
    with _output(ctx):
        pass
    typer.echo("off")


if __name__ == "__main__":
    app()
