import logging
from pathlib import Path

import pytest

from treemap.config import Config, ConfigError, config_from_dict, load_config

from .conftest import REPO_ROOT


def test_defaults_when_no_config_file():
    cfg = load_config()
    assert cfg == Config()
    assert cfg.source is None
    assert cfg.shape == "tree" and cfg.gamma == 2.2


def test_repo_config_yaml_is_valid_and_matches_defaults():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert cfg.to_dict() == Config().to_dict()


def test_partial_sections_merge_with_defaults(write_config):
    write_config("scan:\n  symbol_ms: 300\n")
    cfg = load_config()
    assert cfg.scan.symbol_ms == 300
    assert cfg.scan.round_s == 12.0


def test_empty_file_and_null_section_use_defaults(write_config):
    write_config("")
    assert load_config() == Config()
    write_config("scan:\n")
    assert load_config() == Config()


def test_1x_keys_are_ignored_with_a_warning(write_config, caplog):
    write_config("shape: flat\noutput: wled\ncontrollers:\n  - host: a\ncamera: {type: android}\n"
                 "scan: {camera_fps: 24, symbol_ms: 200}\n", name="config.local.yaml")
    with caplog.at_level(logging.WARNING):
        cfg = load_config()
    assert cfg.shape == "flat" and cfg.scan.symbol_ms == 200
    assert "config.local.yaml: ignoring camera, controllers, output" in caplog.text
    assert "scan.camera_fps" in caplog.text


def test_relative_paths_resolve_against_config_dir(tmp_path, write_config):
    sub = tmp_path / "elsewhere"
    sub.mkdir()
    path = sub / "my.yaml"
    path.write_text("scan:\n  profile: living-room\n")
    cfg = load_config(path)
    assert cfg.base_dir == sub
    assert cfg.scan_dir == sub / "data" / "scans" / "living-room"
    assert cfg.colours_path_for("Pixel 9, back") == sub / "data" / "camera_colours" / "pixel-9-back.json"
    assert cfg.resolve("/abs/file") == Path("/abs/file")


def test_env_var_selects_config(tmp_path, monkeypatch):
    path = tmp_path / "env.yaml"
    path.write_text("shape: flat\n")
    monkeypatch.setenv("TREEMAP_CONFIG", str(path))
    assert load_config().shape == "flat"


def test_explicit_missing_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_invalid_yaml_is_an_error(write_config):
    write_config("shape: [1,\n")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config()


@pytest.mark.parametrize(
    "data, match",
    [
        ({"ledcount": 400}, "unknown key.*ledcount"),
        ([1, 2], "expected a mapping"),
        ({"shape": "cone"}, "shape must be one of tree, flat"),
        ({"scan": {"angles": [0, 90]}}, "unknown key"),
        ({"scan": {"symbol_ms": 10}}, "symbol_ms must be >= 40"),
        ({"scan": {"brightness": 300}}, "brightness must be <= 255"),
        ({"scan": {"fov_deg": 5}}, "fov_deg must be >= 20"),
        ({"scan": {"profile": "a/b"}}, "profile"),
        ({"engine": {"gamma": 5}}, "gamma must be <= 3"),
        ({"server": {"port": 70000}}, "port must be <= 65535"),
        ({"server": {"origins": ["https://a.example/path"]}}, "isn't an origin"),
    ],
)
def test_invalid_values_are_rejected(data, match):
    with pytest.raises(ConfigError, match=match):
        config_from_dict(data)


def test_error_message_names_the_file(write_config):
    path = write_config("shape: cone\n")
    with pytest.raises(ConfigError, match=r"config\.yaml: shape must be"):
        load_config(path)


def test_config_local_yaml_wins_over_config_yaml(write_config):
    write_config("shape: tree\n")
    assert load_config().shape == "tree"
    write_config("shape: flat\n", name="config.local.yaml")
    cfg = load_config()
    assert cfg.shape == "flat" and cfg.source.name == "config.local.yaml"
