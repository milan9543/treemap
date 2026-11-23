"""The ``treemap`` command line: the server, and a virtual WLED to try it with."""

from __future__ import annotations

import asyncio
import logging
import webbrowser
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from treemap import __version__
from treemap.config import CONFIG_ENV_VAR, Config, ConfigError, load_config

app = typer.Typer(
    help="Map where each LED of a WLED tree (or flat layout) is with a phone, and play "
         "effects that use those positions.",
    no_args_is_help=True,
    add_completion=False,
)
sim_app = typer.Typer(help="Try it out without real LEDs.", no_args_is_help=True)
app.add_typer(sim_app, name="sim")


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
            help="Config file. Defaults to ./config.local.yaml, then ./config.yaml, or "
                 "built-in defaults if neither exists.",
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


# -- server ---------------------------------------------------------------------------


@app.command("serve")
def serve(
    ctx: typer.Context,
    port: Annotated[int | None, typer.Option(help="Port. Default: server.port.")] = None,
    host: Annotated[str | None, typer.Option(
        help="Address to listen on. Default: server.host (every interface).")] = None,
    browser: Annotated[bool, typer.Option(help="Open the server's page in a browser.")] = False,
) -> None:
    """Run the server: it drives your WLED controllers, scans them with the phone's scan
    page, and plays effects on them.

    Open its page to add controllers (by address: no config needed) and to get a QR code
    that opens the scan page on the phone. Leave it running.
    """
    import signal
    import time

    from treemap.api import Api, HttpServer, lan_address
    from treemap.pages import pages_dir

    cfg = ctx.obj.config
    port = port or cfg.server.port
    host = host or cfg.server.host
    where = "127.0.0.1" if host in ("127.0.0.1", "localhost") else lan_address()
    api = Api(cfg)
    origins = list(cfg.server.origins)
    scan_origin = "/".join(cfg.server.scan_page.split("/")[:3])  # the QR codes' page
    if "*" not in origins and scan_origin not in origins:
        origins.append(scan_origin)
    try:
        server = HttpServer(api.router, host, port, origins,
                            static=pages_dir(), page="server.html").start()
    except OSError as e:
        api.close()
        fail(f"Can't listen on {host}:{port}: {e.strerror or e}")
    base = f"http://{where}:{server.port}"
    api.url = base
    typer.secho(f"treemap serve on {base}  (Ctrl-C to stop)", fg=typer.colors.GREEN)
    names = ", ".join(d.record.name for d in api.devices.values())
    typer.echo(f"  devices: {names or 'none yet: add your WLED controllers on the page'}")
    typer.secho(f"  the server's page: {base}/", bold=True)
    typer.echo(f"  pages allowed to use it: {', '.join(origins)}")
    if browser:
        webbrowser.open(f"http://127.0.0.1:{server.port}/")

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


# -- virtual WLED ---------------------------------------------------------------------


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
    from treemap.sim.tree import SpecError
    from treemap.sim.virtual_wled import VirtualWled, layout_dict, load_layout, new_layout

    cfg = ctx.obj.config
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
            spec = {} if leds is None else {"strips": [{"leds": n} for n in _split(leds, strips)]}
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
        typer.echo("  To drive it, add this address on `treemap serve`'s page:")
        typer.secho(f"    {d.controller_address}", bold=True)
        typer.echo("  After changing the layout's LED count, the server's page offers to use "
                   "the new count.")
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
