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
from treemap.config import CONFIG_ENV_VAR, SCAN_PAGE, Config, ConfigError, load_config

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
wled_app = typer.Typer(help="WLED controllers.", no_args_is_help=True)
camera_app = typer.Typer(help="The scan camera.", no_args_is_help=True)
app.add_typer(camera_app, name="camera")
app.add_typer(config_app, name="config")
app.add_typer(sim_app, name="sim")
app.add_typer(test_app, name="test")
app.add_typer(wled_app, name="wled")


@dataclass
class State:
    """Per-invocation state. The config is loaded lazily so ``--help`` never needs it."""

    config_path: Path | None
    _config: Config | None = None

    @property
    def raw_config(self) -> Config:
        """The config as loaded, without reading LED counts from the WLED controllers."""
        if self._config is None:
            try:
                self._config = load_config(self.config_path)
            except ConfigError as e:
                fail(f"Config error: {e}", code=2)
        return self._config

    @property
    def config(self) -> Config:
        """The config, with every controller's LED count known (read from WLED where the
        config leaves it out)."""
        cfg = self.raw_config
        if cfg.output == "wled":
            try:
                cfg.controller_layout()
            except ConfigError as e:
                fail(f"Config error: {e}", code=2)
        return cfg


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
    cfg = ctx.obj.raw_config  # still shown when a controller doesn't answer
    source = cfg.source if cfg.source else "built-in defaults (no config.yaml found)"
    typer.secho(f"# source: {source}", fg=typer.colors.BRIGHT_BLACK)
    origin = "the controllers" if cfg.output == "wled" else (
        f"the simulated tree, {cfg.sim_tree_path}" if cfg.sim_tree_path.exists()
        else "sim.strips (no simulated tree yet)")
    try:
        typer.secho(f"# LEDs: {cfg.led_count}, from {origin}", fg=typer.colors.BRIGHT_BLACK)
    except ConfigError as e:
        typer.secho(f"# LEDs: unknown: {e}", fg=typer.colors.YELLOW)
    typer.echo(yaml.safe_dump(cfg.to_dict(), sort_keys=False).rstrip())


# -- sim ------------------------------------------------------------------------------


def _new_tree(cfg: Config, spec=None):
    from treemap.sim.tree import generate_tree, spec_from_config

    tree = generate_tree(spec or spec_from_config(cfg))
    tree.save(cfg.sim_tree_path)
    return tree


def _describe_tree(tree) -> str:
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
    typer.echo(_describe_tree(tree))
    typer.secho(f"saved {cfg.sim_tree_path}", fg=typer.colors.GREEN)


@sim_app.command("view")
def sim_view(
    ctx: typer.Context,
    browser: Annotated[bool, typer.Option(help="Open the viewer in a browser.")] = True,
    port: Annotated[int | None, typer.Option(help="Port. Default: sim.port.")] = None,
    serve: Annotated[bool, typer.Option(
        "--serve", help="Have the virtual phone film for `treemap serve --sim` too, so a "
        "scan started through its API sees the simulated tree.")] = False,
) -> None:
    """Serve the 3D viewer. Leave it running; other commands stream colours to it."""
    from treemap.sim.server import SimServer
    from treemap.sim.tree import SimTree, spec_from_config

    cfg = ctx.obj.config
    if not cfg.sim_tree_path.exists():
        typer.echo("No simulated tree yet, generating one:")
        typer.echo(_describe_tree(_new_tree(cfg)))
    else:
        try:
            SimTree.load(cfg.sim_tree_path)
        except (ValueError, KeyError, TypeError) as e:
            typer.echo(f"Existing tree can't be used ({e}); generating a new one:")
            typer.echo(_describe_tree(_new_tree(cfg)))

    server = SimServer(
        tree_path=cfg.sim_tree_path,
        map_path=cfg.map_path,
        host=cfg.sim.host,
        port=port or cfg.sim.port,
        led_count=lambda: cfg.led_count,  # follows the tree as the viewer regenerates it
        defaults=spec_from_config(cfg),
        make_engine=lambda s: _make_engine(cfg, sim_port=s.port, source="viewer: effects"),
        output_label=_output_label(cfg),
        cfg=cfg,
        make_jobs=lambda s: _make_jobs(cfg, s),
    )

    def ready(s: SimServer) -> None:
        url = s.url
        if serve:
            url += f"?serve=http://127.0.0.1:{_sim_serve_port(cfg)}"
        typer.secho(f"Viewer running at {url}  (Ctrl-C to stop)", fg=typer.colors.GREEN)
        if browser:
            webbrowser.open(url)

    try:
        asyncio.run(server.serve(on_ready=ready))
    except KeyboardInterrupt:
        typer.echo("\nstopped")
    except OSError as e:
        fail(f"Can't start the viewer on {cfg.sim.host}:{server.port}: {e.strerror or e}")


class Shape(str, Enum):
    tree = "tree"
    flat = "flat"


@sim_app.command("wled")
def sim_wled(
    ctx: typer.Context,
    new: Annotated[Shape | None, typer.Option(
        "--new", help="Start with a new layout of this shape (default: the last one).")] = None,
    leds: Annotated[int | None, typer.Option(min=1, help="LEDs in a new layout.")] = None,
    strips: Annotated[int, typer.Option(min=1, max=8, help="Strips in a new layout.")] = 2,
    port: Annotated[int, typer.Option(help="HTTP port (WLED's JSON API and the page).")] = 8780,
    browser: Annotated[bool, typer.Option(help="Open the page in a browser.")] = True,
) -> None:
    """A virtual WLED controller: a simulated tree or flat layout on this screen.

    `treemap serve` drives it like real LEDs (DDP on UDP 4048, the LED count from its
    /json/info). Walk round it on screen (click, then WASD, mouse, Space, Shift) while the
    phone's scan page films the screen. New layouts can be made on the page too.
    """
    from treemap.api import lan_address
    from treemap.sim.tree import SpecError, spec_from_config
    from treemap.sim.virtual_wled import VirtualWled, layout_dict, load_layout, new_layout

    cfg = ctx.obj.raw_config
    path = cfg.resolve(Path("data") / "virtual_wled.json")
    layout = None
    if new is None and path.exists():
        try:
            layout = load_layout(path)
        except (ValueError, KeyError, TypeError) as e:
            typer.echo(f"The saved layout can't be used ({e}); making a new one.")
    if layout is None:
        shape = (new or Shape.tree).value
        try:
            if leds is not None:
                spec = {"strips": [{"leds": n} for n in _split(leds, strips)]}
            elif shape == "tree":
                spec = spec_from_config(cfg).to_dict()
            else:
                spec = {}
            layout = new_layout(shape, spec)
        except SpecError as e:
            fail(str(e), code=2)
        layout.save(path)
    device = VirtualWled(path, port=port, address=lan_address())
    device.use(layout)

    def ready(d: VirtualWled) -> None:
        url = f"http://127.0.0.1:{d.port}/"
        d_shape = layout_dict(d.layout)["shape"] if d.layout else "?"
        typer.secho(f"Virtual WLED: {d.led_count} LEDs ({d_shape}) at {url}  (Ctrl-C to stop)",
                    fg=typer.colors.GREEN)
        typer.echo(f"  DDP on UDP {d.ddp_port}; WLED's JSON API at http://{d.address}:{d.port}/json")
        typer.echo("  For `treemap serve`, in config.local.yaml:")
        typer.secho(f"    output: wled\n    {d.controller_line}", bold=True)
        typer.echo("  Restart `treemap serve` after changing the layout's LED count.")
        if browser:
            webbrowser.open(url)

    try:
        asyncio.run(device.serve(on_ready=ready))
    except KeyboardInterrupt:
        typer.echo("\nstopped")
    except OSError as e:
        fail(f"Can't start the virtual WLED (HTTP port {port}, DDP port 4048): "
             f"{e.strerror or e}. Is another one, or real WLED software, running here?")


def _split(total: int, parts: int) -> list[int]:
    from treemap.sim.tree import split_counts

    if total < parts:
        fail(f"{total} LEDs can't fill {parts} strips", code=2)
    return split_counts(total, parts)


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

    return lambda: create_output(cfg, sim_port, source)


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
        shown = time.monotonic()
        while engine.running and (end is None or time.monotonic() < end):
            engine.wait(0.1)
            if time.monotonic() - shown >= 2:
                shown = time.monotonic()
                typer.echo(f"\r{_timing_line(engine.timing())}   ", nl=False)
    except KeyboardInterrupt:
        typer.echo("\nstopped")
    finally:
        typer.echo()
        engine.stop()
    if engine.error:
        fail(engine.error)


def _timing_line(t: dict) -> str:
    """The engine's timing in one line: frame rate, render and send times, late frames."""
    if t["fps"] is None:
        return "starting…"
    line = (f"{t['fps']:.1f}/{t['fps_target']:g} fps, render {t['render_ms']['median']:.1f} ms "
            f"(max {t['render_ms']['max']:.1f}), send {t['send_ms']['median']:.1f} ms "
            f"(max {t['send_ms']['max']:.1f}), {t['late']} late")
    return typer.style(line + " SLOW", fg=typer.colors.YELLOW) if t["slow"] else line


# -- server ---------------------------------------------------------------------------


def _sim_serve_port(cfg: Config) -> int:
    """`treemap serve --sim`'s port: server.port, unless the viewer has it."""
    return cfg.server.port if cfg.server.port != cfg.sim.port else cfg.sim.port + 1


@app.command("serve")
def serve(
    ctx: typer.Context,
    port: Annotated[int | None, typer.Option(help="Port. Default: server.port.")] = None,
    host: Annotated[str | None, typer.Option(
        help="Address to listen on. Default: server.host (every interface).")] = None,
    sim: Annotated[bool, typer.Option(
        "--sim", help="Drive the simulated tree in the viewer instead of the configured "
        "LEDs, for development. Open the viewer with `treemap sim view --serve` to scan "
        "it through the API.")] = False,
) -> None:
    """Serve the API the phone's scan page uses, on the local network.

    The LEDs, the scan and the effects all run here; the page on the phone drives them.
    Leave it running.
    """
    import copy
    import signal
    import time

    from treemap.api import Api, HttpServer, lan_address
    from treemap.outputs import OutputError, create_output

    if sim:
        cfg = copy.copy(ctx.obj.raw_config)  # the controllers aren't needed
        cfg.output, cfg.shape = "sim", "tree"  # the simulator only grows trees
        # the viewer's page may use the API: its virtual phone uploads the frames
        viewer = f"http://{cfg.sim.host}:{cfg.sim.port}"
        cfg.server = copy.copy(cfg.server)
        cfg.server.origins = [*cfg.server.origins, viewer, viewer.replace("127.0.0.1", "localhost")]
        port = port or _sim_serve_port(cfg)
    else:
        cfg = ctx.obj.config
        port = port or cfg.server.port
    host = host or cfg.server.host
    if cfg.output == "sim" and port == cfg.sim.port:
        fail(f"the simulator's viewer uses port {port}; serve on another one "
             f"(--port {port + 1}, or server.port in the config)", code=2)
    try:
        output = create_output(cfg, source="treemap serve", mirror=False)
    except OutputError as e:
        fail(str(e))
    api = Api(cfg, output)
    try:
        server = HttpServer(api.router, host, port, cfg.server.origins).start()
    except OSError as e:
        api.close()
        fail(f"Can't listen on {host}:{port}: {e.strerror or e}")
    where = "127.0.0.1" if host in ("127.0.0.1", "localhost") else lan_address()
    base = f"http://{where}:{server.port}"
    typer.secho(f"treemap serve on {base}  (Ctrl-C to stop)", fg=typer.colors.GREEN)
    typer.echo(f"  {api.n} LEDs on {_output_label(cfg)}; API at {base}/api/v1/info")
    typer.echo(f"  pages allowed to use it: {', '.join(cfg.server.origins) or 'none'}")
    if SCAN_PAGE in cfg.server.origins or "*" in cfg.server.origins:
        typer.secho(f"  scan page (Chrome on an Android phone): {SCAN_PAGE}/?server={base}",
                    bold=True)
    if sim:
        typer.echo("  to scan the simulated tree through the API: `treemap sim view --serve`, "
                   "walk round it (f), then POST /api/v1/scan/start")

    def terminate(signum, frame) -> None:  # e.g. `docker stop`: shut down as for Ctrl-C
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        typer.echo("\nstopping")
    finally:
        server.stop()
        api.close()


# -- scan -----------------------------------------------------------------------------


@app.command("scan")
def scan(
    ctx: typer.Context,
    rounds: Annotated[
        int | None,
        typer.Option(min=1, help="Rounds to run. Default: scan.max_rounds (it also stops "
                     "once every LED is ok).", show_default=False),
    ] = None,
) -> None:
    """Flash every LED's code while you walk round the tree with the camera.

    A scan starts over: earlier rounds are forgotten. First there's a countdown of
    scan.countdown_s to point the camera at the LEDs, then the phone's exposure is set
    and its colours measured. Each round flashes for scan.round_s seconds, solves the positions from every round so
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
            tree_map = workflow.run_scan(cfg, out, rounds=rounds,
                                         on_update=_scan_progress, on_message=typer.echo)
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
    if phase == "countdown":
        typer.echo(f"\rstarting in {u['remaining']:3.0f} s: point the camera at the LEDs   ",
                   nl=False)
    elif phase == "exposure":
        typer.echo("\rsetting the camera's exposure…" + " " * 30)
    elif phase == "colours":
        typer.echo("measuring how the camera sees the colours…")
    elif phase == "flashing":
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
        raise typer.BadParameter(f"must be below the number of LEDs ({n})", param_hint="INDEX")
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
    from treemap.outputs import OutputError, create_output

    cfg = ctx.obj.config
    try:
        out = create_output(cfg)
    except OutputError as e:
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
        raise typer.BadParameter(f"index must be below the number of LEDs ({n})", param_hint="INDEX")
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


# -- camera ---------------------------------------------------------------------------


@camera_app.command("check")
def camera_check(
    ctx: typer.Context,
    brightness: Annotated[
        int | None, typer.Option(min=1, max=255, help="LED brightness to try, 0-255. "
                                 "Default: scan.brightness.", show_default=False)
    ] = None,
) -> None:
    """Check the camera can scan: its frame rate, and whether it reads the LEDs' colours.

    Point the phone at the LEDs first. The LEDs turn white while the camera's exposure
    and white balance adjust (then they're locked), then show red, green, blue and white
    in turn. One frame of each is saved in data/camera_check/.
    """
    import cv2

    from treemap.cameras import CameraError, create_camera
    from treemap.cameras.check import advice, colour_check, fix_exposure, measure_fps

    cfg = ctx.obj.config
    brightness = brightness or cfg.scan.brightness
    try:
        camera = create_camera(cfg)
    except CameraError as e:
        fail(str(e))
    with camera, _output(ctx) as out:
        where = cfg.camera.url if cfg.camera.type == "android" else "the viewer's phone"
        typer.echo(f"camera: {cfg.camera.type} ({where})")
        settings = camera.settings() if hasattr(camera, "settings") else None
        if settings:
            typer.echo("  " + ", ".join(f"{k} {settings[k]}" for k in (
                "video_size", "quality", "exposure_lock", "whitebalance_lock", "manual_sensor",
                "exposure_ns", "iso", "whitebalance", "focusmode") if k in settings))
        done = fix_exposure(camera, out, brightness)
        if done:
            typer.echo(f"  {done}")
        typer.echo("measuring the frame rate…")
        fps, size = measure_fps(camera)
        if size is None:
            fail("no frames arrived from the camera")
        typer.echo(f"  {fps:.1f} frames/s at {size[0]}x{size[1]}")
        typer.echo(f"showing each colour at scan.brightness {brightness}…")
        results, model = colour_check(camera, out, brightness)

    folder = cfg.resolve("data/camera_check")
    folder.mkdir(parents=True, exist_ok=True)
    for r in results:
        share = f"{r.share:.0%} read right" if r.share == r.share else "-"
        misread = f", else {r.misread_as}" if r.misread_as and r.share < 1 else ""
        typer.echo(f"  {r.name:<6} {r.blobs:>4} LEDs seen, {share}{misread}")
        if r.sample is not None:
            cv2.imwrite(str(folder / f"{r.name}.jpg"), r.sample)
    typer.secho(f"sample frames in {folder}", fg=typer.colors.BRIGHT_BLACK)
    if model is not None and min(r.blobs for r in results) < 10:
        model = None  # too few LEDs to measure from: keep the last good measurement
    if model is not None:
        from treemap.workflow import save_colours

        save_colours(cfg, model, camera, results)
        typer.echo(f"saved how this camera sees the colours in {cfg.colours_path}")
    else:
        typer.secho("the colours couldn't be measured, so nothing was saved",
                    fg=typer.colors.YELLOW)
    tips = advice(fps, size, results, model, brightness)
    for tip in tips:
        typer.secho(f"warning: {tip}", fg=typer.colors.YELLOW)
    if not tips:
        typer.secho("the camera is ready to scan", fg=typer.colors.GREEN)


# -- WLED -----------------------------------------------------------------------------


@wled_app.command("check")
def wled_check(ctx: typer.Context) -> None:
    """Ask each controller in the config whether its WLED settings fit."""
    from treemap.outputs import OutputError
    from treemap.outputs.wled import check_problems, fetch_cfg, fetch_state

    cfg = ctx.obj.raw_config  # a controller that doesn't answer is reported, not fatal
    unreachable = 0
    for i, c in enumerate(cfg.controllers):
        start = "after the previous one" if c.start is None else f"from {c.start}"
        count = "count from WLED" if c.count is None else f"{c.count} LEDs"
        typer.secho(f"controllers[{i}] {c.host} ({count}, {start}"
                    f"{', reversed' if c.reverse else ''})", bold=True)
        try:
            data = fetch_state(c.host)
        except OutputError as e:
            typer.secho(f"  {e}", fg=typer.colors.RED)
            unreachable += 1
            continue
        data["cfg"] = fetch_cfg(c.host)
        info, state = data["info"], data.get("state", {})
        typer.echo(f"  {info.get('name', 'WLED')} {info.get('ver', '')} at "
                   f"{info.get('ip', c.host)}: {info.get('leds', {}).get('count', '?')} LEDs, "
                   f"{'on' if state.get('on') else 'off'}, brightness {state.get('bri', '?')}/255")
        problems = check_problems(c, data, i)
        for p in problems:
            typer.secho(f"  warning: {p}", fg=typer.colors.YELLOW)
        if not problems:
            typer.secho("  ok", fg=typer.colors.GREEN)
    if not unreachable:
        try:
            layout = cfg.controller_layout()
        except ConfigError as e:
            typer.secho(f"\n{e}", fg=typer.colors.RED)
            raise typer.Exit(1) from None
        typer.echo("\n" + "; ".join(
            f"{c.host}: LEDs {c.start}-{c.start + c.count - 1}" for c in layout))
    if cfg.output != "wled":
        typer.echo("\nSet `output: wled` in the config to send colours to the controllers.")
    if unreachable:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
