"""The ``treemap`` command line."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

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
app.add_typer(config_app, name="config")


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
                typer.secho(f"Config error: {e}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2) from None
        return self._config


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
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show the version."
        ),
    ] = False,
) -> None:
    ctx.obj = State(config_path=config)


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    """Validate the config and print the effective values (file merged with defaults)."""
    cfg = ctx.obj.config
    source = cfg.source if cfg.source else "built-in defaults (no config.yaml found)"
    typer.secho(f"# source: {source}", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(yaml.safe_dump(cfg.to_dict(), sort_keys=False).rstrip())


if __name__ == "__main__":
    app()
