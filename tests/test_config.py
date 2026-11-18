from pathlib import Path

import pytest

from treemap.config import Config, ConfigError, config_from_dict, load_config

from .conftest import REPO_ROOT


def test_defaults_when_no_config_file():
    cfg = load_config()
    assert cfg == Config()
    assert cfg.source is None
    assert cfg.led_count == 400
    assert cfg.output == "sim"
    assert cfg.camera.type == "sim"


def test_repo_config_yaml_is_valid_and_matches_defaults():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert cfg.to_dict() == Config().to_dict()


def test_partial_sections_merge_with_defaults(write_config):
    write_config("scan:\n  settle_ms: 300\nsim:\n  seed: 7\n")
    cfg = load_config()
    assert cfg.scan.settle_ms == 300
    assert cfg.scan.angles == [0.0, 90.0, 180.0, 270.0]
    assert cfg.sim.seed == 7
    assert cfg.sim.port == 8765


def test_empty_file_and_null_section_use_defaults(write_config):
    write_config("")
    assert load_config() == Config()
    write_config("camera:\n")
    assert load_config() == Config()


def test_two_controllers(write_config):
    write_config(
        "output: wled\n"
        "controllers:\n"
        "  - {host: a, start: 0, count: 200}\n"
        "  - {host: b, start: 200, count: 200, reverse: true}\n"
    )
    cfg = load_config()
    assert [(c.host, c.start, c.count, c.reverse) for c in cfg.controllers] == [
        ("a", 0, 200, False),
        ("b", 200, 200, True),
    ]


def test_relative_paths_resolve_against_config_dir(tmp_path, write_config):
    sub = tmp_path / "elsewhere"
    sub.mkdir()
    path = sub / "my.yaml"
    path.write_text("scan:\n  profile: living-room\n")
    cfg = load_config(path)
    assert cfg.base_dir == sub
    assert cfg.resolve(cfg.sim.tree_file) == sub / "data" / "sim_tree.json"
    assert cfg.scan_dir == sub / "data" / "scans" / "living-room"
    assert cfg.resolve("/abs/file") == Path("/abs/file")


def test_env_var_selects_config(tmp_path, monkeypatch):
    path = tmp_path / "env.yaml"
    path.write_text("led_count: 50\ncontrollers: []\n")
    monkeypatch.setenv("TREEMAP_CONFIG", str(path))
    assert load_config().led_count == 50


def test_explicit_missing_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_invalid_yaml_is_an_error(write_config):
    write_config("led_count: [1,\n")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config()


@pytest.mark.parametrize(
    "data, match",
    [
        ({"ledcount": 400}, "unknown key.*ledcount"),
        ({"camera": {"typ": "sim"}}, r"camera: unknown key.*typ"),
        ([1, 2], "expected a mapping"),
        ({"led_count": 0}, "led_count must be >= 1"),
        ({"led_count": "400"}, "led_count must be an integer"),
        ({"led_count": True}, "led_count must be an integer"),
        ({"output": "dmx"}, "output must be one of sim, wled"),
        ({"controllers": {"host": "a"}}, "controllers: expected a list"),
        ({"controllers": [{"start": 0}]}, r"controllers\[0\]: missing required key.*host"),
        ({"controllers": [{"host": "a", "count": 500}]}, "beyond led_count"),
        ({"controllers": [{"host": "a", "reverse": "yes"}]}, "reverse must be true or false"),
        (
            {"controllers": [{"host": "a", "count": 250}, {"host": "b", "start": 200, "count": 200}]},
            "overlap",
        ),
        ({"output": "wled", "controllers": []}, "needs at least one entry"),
        ({"camera": {"type": "webcam"}}, "camera.type must be one of"),
        ({"camera": {"type": "android"}}, "needs camera.url"),
        ({"scan": {"angles": []}}, "non-empty list"),
        ({"scan": {"angles": [0, 360]}}, "duplicate"),
        ({"scan": {"angles": [0, "x"]}}, "non-number"),
        ({"scan": {"brightness": 300}}, "brightness must be <= 255"),
        ({"scan": {"min_confidence": 2}}, "min_confidence must be <= 1"),
        ({"scan": {"profile": "a/b"}}, "profile"),
        ({"sim": {"port": 70000}}, "port must be <= 65535"),
        ({"sim": {"seed": 1.5}}, "seed must be an integer"),
    ],
)
def test_invalid_values_are_rejected(data, match):
    with pytest.raises(ConfigError, match=match):
        config_from_dict(data)


def test_error_message_names_the_file(write_config):
    path = write_config("output: dmx\n")
    with pytest.raises(ConfigError, match=r"config\.yaml: output must be"):
        load_config(path)
