import yaml
from typer.testing import CliRunner

from treemap import __version__
from treemap.cli import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "config" in result.output


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_does_not_load_a_broken_config(write_config):
    write_config("output: dmx\n")
    assert runner.invoke(app, ["--help"]).exit_code == 0
    assert runner.invoke(app, ["config", "--help"]).exit_code == 0


def test_config_show_defaults():
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert "built-in defaults" in result.output
    body = yaml.safe_load(result.output)
    assert body["led_count"] == 400
    assert body["output"] == "sim"


def test_config_show_with_file(write_config):
    path = write_config("led_count: 200\ncontrollers: []\n", name="custom.yaml")
    result = runner.invoke(app, ["--config", str(path), "config", "show"])
    assert result.exit_code == 0, result.output
    assert str(path) in result.output
    assert yaml.safe_load(result.output)["led_count"] == 200


def test_config_show_reports_errors(write_config):
    write_config("output: dmx\n")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 2
    assert "output must be one of" in result.output
