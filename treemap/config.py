"""Loading and validating ``config.yaml``.

Every key is optional. Missing keys fall back to the dataclass defaults, unknown keys are
rejected (so a typo doesn't silently do nothing), and values are validated on load.
"""

from __future__ import annotations

import os
from dataclasses import MISSING, asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")
CONFIG_ENV_VAR = "TREEMAP_CONFIG"

OUTPUT_TYPES = ("sim", "wled")
CAMERA_TYPES = ("sim", "android")


class ConfigError(ValueError):
    """Raised when the config file is missing required structure or has invalid values."""


@dataclass
class Controller:
    """One WLED controller owning global LEDs ``[start, start + count)``."""

    host: str
    start: int = 0
    count: int = 400
    reverse: bool = False


@dataclass
class CameraConfig:
    type: str = "sim"
    url: str | None = None


@dataclass
class ScanConfig:
    profile: str = "default"
    angles: list[float] = field(default_factory=lambda: [0.0, 90.0, 180.0, 270.0])
    settle_ms: int = 150
    brightness: int = 255
    min_confidence: float = 0.3


@dataclass
class EngineConfig:
    fps: float = 40.0
    brightness: float = 0.8
    crossfade: float = 0.6  # seconds


@dataclass
class StripConfig:
    """One strip on the simulated tree (see ``treemap.sim.tree.StripSpec``)."""

    leds: int
    length: float | None = None
    start: str = "auto"


@dataclass
class SimConfig:
    seed: int | None = None
    strips: list[StripConfig] | None = None  # None = led_count split over 2 strips
    height: float | None = None
    radius: float | None = None
    layout: str = "auto"
    quirks: bool = True
    tree_file: str = "data/sim_tree.json"
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass
class Config:
    led_count: int = 400
    output: str = "sim"
    controllers: list[Controller] = field(
        default_factory=lambda: [Controller(host="wled-tree.local", start=0, count=400)]
    )
    camera: CameraConfig = field(default_factory=CameraConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    sim: SimConfig = field(default_factory=SimConfig)

    # Not a config key: directory relative paths are resolved against.
    base_dir: Path = field(default_factory=Path.cwd, repr=False, compare=False)
    # Not a config key: the file this was loaded from, if any.
    source: Path | None = field(default=None, repr=False, compare=False)

    def resolve(self, path: str | Path) -> Path:
        """Resolve a path from the config relative to the config file's directory."""
        p = Path(path).expanduser()
        return p if p.is_absolute() else self.base_dir / p

    @property
    def scan_dir(self) -> Path:
        return self.resolve(Path("data") / "scans" / self.scan.profile)

    @property
    def map_path(self) -> Path:
        """The reconstructed map written by ``treemap reconstruct``."""
        return self.resolve(Path("data") / "tree_map.json")

    @property
    def sim_tree_path(self) -> Path:
        return self.resolve(self.sim.tree_file)

    def to_dict(self) -> dict[str, Any]:
        """The config as plain data, without the non-key fields."""
        d = asdict(self)
        d.pop("base_dir")
        d.pop("source")
        return d

    def validate(self) -> None:
        _check_int("led_count", self.led_count, minimum=1)
        _check_choice("output", self.output, OUTPUT_TYPES)

        for i, c in enumerate(self.controllers):
            where = f"controllers[{i}]"
            if not isinstance(c.host, str) or not c.host:
                raise ConfigError(f"{where}.host must be a non-empty string")
            _check_int(f"{where}.start", c.start, minimum=0)
            _check_int(f"{where}.count", c.count, minimum=1)
            _check_bool(f"{where}.reverse", c.reverse)
            if c.start + c.count > self.led_count:
                raise ConfigError(
                    f"{where} covers LEDs {c.start}..{c.start + c.count - 1}, "
                    f"beyond led_count={self.led_count}"
                )
        ranges = sorted((c.start, c.start + c.count, i) for i, c in enumerate(self.controllers))
        for (_, end_a, ia), (start_b, _, ib) in zip(ranges, ranges[1:]):
            if start_b < end_a:
                raise ConfigError(f"controllers[{ia}] and controllers[{ib}] overlap")
        if self.output == "wled" and not self.controllers:
            raise ConfigError("output: wled needs at least one entry in controllers")

        _check_choice("camera.type", self.camera.type, CAMERA_TYPES)
        if self.camera.url is not None and not isinstance(self.camera.url, str):
            raise ConfigError("camera.url must be a string or null")
        if self.camera.type == "android" and not self.camera.url:
            raise ConfigError("camera.type: android needs camera.url (e.g. http://phone:8080)")

        s = self.scan
        if not isinstance(s.profile, str) or not s.profile or "/" in s.profile:
            raise ConfigError("scan.profile must be a non-empty name without '/'")
        if not isinstance(s.angles, list) or not s.angles:
            raise ConfigError("scan.angles must be a non-empty list of degrees")
        for a in s.angles:
            if isinstance(a, bool) or not isinstance(a, (int, float)):
                raise ConfigError(f"scan.angles contains a non-number: {a!r}")
        if len({float(a) % 360 for a in s.angles}) != len(s.angles):
            raise ConfigError("scan.angles contains duplicate angles")
        _check_int("scan.settle_ms", s.settle_ms, minimum=0)
        _check_int("scan.brightness", s.brightness, minimum=1, maximum=255)
        _check_number("scan.min_confidence", s.min_confidence, minimum=0.0, maximum=1.0)

        _check_number("engine.fps", self.engine.fps, minimum=1, maximum=120)
        _check_number("engine.brightness", self.engine.brightness, minimum=0, maximum=1)
        _check_number("engine.crossfade", self.engine.crossfade, minimum=0, maximum=10)

        sim = self.sim
        if sim.seed is not None:
            _check_int("sim.seed", sim.seed, minimum=0)
        for i, st in enumerate(sim.strips or []):
            _check_int(f"sim.strips[{i}].leds", st.leds, minimum=1)
            if st.length is not None:
                _check_number(f"sim.strips[{i}].length", st.length)
        for key in ("height", "radius"):
            if getattr(sim, key) is not None:
                _check_number(f"sim.{key}", getattr(sim, key))
        _check_bool("sim.quirks", sim.quirks)
        if sim.strips is not None:
            total = sum(st.leds for st in sim.strips)
            if total != self.led_count:
                raise ConfigError(
                    f"sim.strips add up to {total} LEDs but led_count is {self.led_count}"
                )
        from treemap.sim.tree import SpecError, spec_from_config  # lazy: pulls in numpy

        try:
            spec_from_config(self)
        except SpecError as e:
            raise ConfigError(f"sim: {e}") from None
        if not isinstance(self.sim.tree_file, str) or not self.sim.tree_file:
            raise ConfigError("sim.tree_file must be a non-empty path")
        if not isinstance(self.sim.host, str) or not self.sim.host:
            raise ConfigError("sim.host must be a non-empty string")
        _check_int("sim.port", self.sim.port, minimum=1, maximum=65535)


def find_config_path(explicit: str | Path | None = None) -> Path | None:
    """Pick the config file: explicit path, then $TREEMAP_CONFIG, then ./config.yaml.

    An explicit or env path must exist; ./config.yaml is optional (None if absent).
    """
    chosen = explicit or os.environ.get(CONFIG_ENV_VAR)
    if chosen:
        path = Path(chosen).expanduser()
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return path
    return DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.is_file() else None


def load_config(path: str | Path | None = None) -> Config:
    """Load, merge with defaults and validate the config. See :func:`find_config_path`."""
    found = find_config_path(path)
    if found is None:
        cfg = Config()
        cfg.validate()
        return cfg

    try:
        raw = yaml.safe_load(found.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{found}: invalid YAML: {e}") from e
    cfg = config_from_dict(raw, where=str(found))
    cfg.base_dir = found.resolve().parent
    cfg.source = found
    return cfg


def config_from_dict(data: Any, where: str = "config") -> Config:
    """Build and validate a :class:`Config` from parsed YAML data."""
    try:
        cfg = _build(Config, data, "", skip={"base_dir", "source"})
        cfg.validate()
    except ConfigError as e:
        raise ConfigError(f"{where}: {e}") from None
    return cfg


# Nested dataclass types for list/section fields, keyed by (owner class, field name).
_NESTED: dict[tuple[type, str], tuple[type, bool]] = {
    (Config, "controllers"): (Controller, True),
    (Config, "camera"): (CameraConfig, False),
    (Config, "scan"): (ScanConfig, False),
    (Config, "engine"): (EngineConfig, False),
    (Config, "sim"): (SimConfig, False),
    (SimConfig, "strips"): (StripConfig, True),
}


def _build(cls: type, data: Any, where: str, skip: frozenset[str] | set[str] = frozenset()) -> Any:
    label = where or "top level"
    if not isinstance(data, dict):
        raise ConfigError(f"{label}: expected a mapping, got {type(data).__name__}")
    assert is_dataclass(cls)
    known = {f.name: f for f in fields(cls) if f.name not in skip}
    unknown = sorted(set(map(str, data)) - set(known))
    if unknown:
        raise ConfigError(
            f"{label}: unknown key(s) {', '.join(unknown)}; "
            f"expected one of {', '.join(known)}"
        )

    kwargs: dict[str, Any] = {}
    for name, value in data.items():
        nested = _NESTED.get((cls, name))
        sub = f"{where}.{name}" if where else name
        if nested is None:
            kwargs[name] = value
        elif nested[1]:  # list of dataclasses
            if value is None and known[name].default is None:
                kwargs[name] = None  # optional list left unset
                continue
            if not isinstance(value, list):
                raise ConfigError(f"{sub}: expected a list, got {type(value).__name__}")
            kwargs[name] = [_build(nested[0], v, f"{sub}[{i}]") for i, v in enumerate(value)]
        else:
            kwargs[name] = _build(nested[0], value if value is not None else {}, sub)

    missing = [
        n for n, f in known.items()
        if n not in kwargs and f.default is MISSING and f.default_factory is MISSING
    ]
    if missing:
        raise ConfigError(f"{label}: missing required key(s) {', '.join(missing)}")
    return cls(**kwargs)


def _check_int(name: str, v: Any, minimum: int | None = None, maximum: int | None = None) -> None:
    if isinstance(v, bool) or not isinstance(v, int):
        raise ConfigError(f"{name} must be an integer, got {v!r}")
    _check_range(name, v, minimum, maximum)


def _check_number(
    name: str, v: Any, minimum: float | None = None, maximum: float | None = None
) -> None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ConfigError(f"{name} must be a number, got {v!r}")
    _check_range(name, v, minimum, maximum)


def _check_range(name: str, v: float, minimum: float | None, maximum: float | None) -> None:
    if minimum is not None and v < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {v}")
    if maximum is not None and v > maximum:
        raise ConfigError(f"{name} must be <= {maximum}, got {v}")


def _check_bool(name: str, v: Any) -> None:
    if not isinstance(v, bool):
        raise ConfigError(f"{name} must be true or false, got {v!r}")


def _check_choice(name: str, v: Any, choices: tuple[str, ...]) -> None:
    if v not in choices:
        raise ConfigError(f"{name} must be one of {', '.join(choices)}, got {v!r}")
