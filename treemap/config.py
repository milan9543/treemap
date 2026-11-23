"""Loading and validating ``config.yaml``.

Every key is optional. Missing keys fall back to the dataclass defaults, unknown keys are
rejected (so a typo doesn't silently do nothing), and values are validated on load.
Keys only the 1.x commands used (``RETIRED``) are ignored, with a warning.

The number of LEDs isn't a key: ``treemap serve`` sets :attr:`Config.led_count` for each
device, from its WLED.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import MISSING, asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")
LOCAL_CONFIG_PATH = Path("config.local.yaml")  # your own settings, not in git
CONFIG_ENV_VAR = "TREEMAP_CONFIG"

SHAPES = ("tree", "flat")
MAX_LEDS = 5000  # the most LEDs anything here handles (also the sim generator's limit)
# Keys of the 1.x commands (`treemap scan`, `treemap run`, `treemap sim view`, ...),
# which are gone: ignored, with a warning, so an old config.local.yaml still loads.
RETIRED = {"": {"output", "controllers", "camera", "sim", "led_count"},
           "scan": {"camera_fps"}}

log = logging.getLogger(__name__)


class ConfigError(ValueError):
    """Raised when the config file is missing required structure or has invalid values."""


@dataclass
class ScanConfig:
    profile: str = "default"
    symbol_ms: int = 150  # how long each colour of the code shows
    brightness: int = 160  # 0-255 while flashing; lower keeps a real camera from clipping
    round_s: float = 12.0  # seconds of flashing per round
    status_s: float = 4.0  # seconds of status colours between rounds
    max_rounds: int = 10  # stop after this many rounds (or when every LED is ok)
    countdown_s: float = 5.0  # seconds to point the camera at the LEDs before a scan
    fov_deg: float = 65.0  # the phone camera's horizontal field of view: a starting guess


@dataclass
class EngineConfig:
    fps: float = 40.0
    brightness: float = 0.8
    crossfade: float = 0.6  # seconds
    gamma: float | None = None  # None: 2.2 (LEDs are linear; a screen uses 1)


SCAN_PAGE = "https://treemap-scan.pages.dev"  # the hosted scan page (scanapp/)
DEFAULT_ORIGINS = (SCAN_PAGE, "https://treemap-spike.pages.dev", "http://localhost:5173")


@dataclass
class ServerConfig:
    """``treemap serve``: the HTTP API the phone's page talks to."""

    host: str = "0.0.0.0"  # every network interface, so the phone can reach it
    port: int = 8765
    # Web pages allowed to use the API from a browser (CORS). "*" allows any.
    origins: list[str] = field(default_factory=lambda: list(DEFAULT_ORIGINS))
    # The scan page the server's QR codes open (on the phone).
    scan_page: str = SCAN_PAGE


@dataclass
class Config:
    # The shape a device's map has until a scan says otherwise. tree: LEDs wound round a
    # tree, mapped in 3D. flat: LEDs laid on the floor (or on a wall), mapped in 2D.
    shape: str = "tree"
    scan: ScanConfig = field(default_factory=ScanConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    # Not a config key: directory relative paths are resolved against.
    base_dir: Path = field(default_factory=Path.cwd, repr=False, compare=False)
    # Not a config key: the file this was loaded from, if any.
    source: Path | None = field(default=None, repr=False, compare=False)
    # Not a config key: where one device's map and scans are kept (`treemap serve` drives
    # several); None: data/ itself.
    device_dir: Path | None = field(default=None, repr=False, compare=False)
    # Not a config key: the device's LED count (from its WLED).
    led_count: int = field(default=0, repr=False, compare=False)

    def resolve(self, path: str | Path) -> Path:
        """Resolve a path from the config relative to the config file's directory."""
        p = Path(path).expanduser()
        return p if p.is_absolute() else self.base_dir / p

    @property
    def scan_dir(self) -> Path:
        return (self.device_dir or self.resolve("data")) / "scans" / self.scan.profile

    def colours_path_for(self, camera_id: str) -> Path:
        """Where a phone's measured colours are kept (``camera_id``: its model and
        camera, as the scan page names it)."""
        slug = re.sub(r"[^a-z0-9]+", "-", camera_id.lower()).strip("-")[:80] or "camera"
        return self.resolve(Path("data") / "camera_colours" / f"{slug}.json")

    @property
    def map_path(self) -> Path:
        """The device's map, written by its scans."""
        return (self.device_dir or self.resolve("data")) / "tree_map.json"

    @property
    def library_path(self) -> Path:
        """Favourite effects and playlists (see :mod:`treemap.library`)."""
        return self.resolve(Path("data") / "library.json")

    @property
    def gamma(self) -> float:
        """engine.gamma, or 2.2: LEDs are linear, so without it fades look too bright.
        ``treemap serve`` uses 1 for the virtual WLED, a screen with its own gamma."""
        return 2.2 if self.engine.gamma is None else float(self.engine.gamma)

    def to_dict(self) -> dict[str, Any]:
        """The config as plain data, without the non-key fields."""
        d = asdict(self)
        for key in ("base_dir", "source", "device_dir", "led_count"):
            d.pop(key)
        return d

    def validate(self) -> None:
        _check_choice("shape", self.shape, SHAPES)

        srv = self.server
        if not isinstance(srv.host, str) or not srv.host:
            raise ConfigError("server.host must be a non-empty string")
        _check_int("server.port", srv.port, minimum=1, maximum=65535)
        if not isinstance(srv.origins, list):
            raise ConfigError("server.origins must be a list of web page origins")
        for o in srv.origins:
            if o != "*" and not (isinstance(o, str) and ORIGIN_RE.fullmatch(o)):
                raise ConfigError(f"server.origins: {o!r} isn't an origin like "
                                  "https://example.com or http://localhost:5173 (no path)")
        if not (isinstance(srv.scan_page, str) and re.fullmatch(r"https?://\S+", srv.scan_page)):
            raise ConfigError("server.scan_page must be the scan page's address, like "
                              f"{SCAN_PAGE}")

        s = self.scan
        if not isinstance(s.profile, str) or not s.profile or "/" in s.profile:
            raise ConfigError("scan.profile must be a non-empty name without '/'")
        _check_int("scan.symbol_ms", s.symbol_ms, minimum=40, maximum=2000)
        _check_int("scan.brightness", s.brightness, minimum=1, maximum=255)
        _check_number("scan.round_s", s.round_s, minimum=2, maximum=600)
        _check_number("scan.status_s", s.status_s, minimum=0, maximum=60)
        _check_int("scan.max_rounds", s.max_rounds, minimum=1)
        _check_number("scan.countdown_s", s.countdown_s, minimum=0, maximum=60)
        _check_number("scan.fov_deg", s.fov_deg, minimum=20, maximum=150)

        _check_number("engine.fps", self.engine.fps, minimum=1, maximum=120)
        _check_number("engine.brightness", self.engine.brightness, minimum=0, maximum=1)
        _check_number("engine.crossfade", self.engine.crossfade, minimum=0, maximum=10)
        if self.engine.gamma is not None:
            _check_number("engine.gamma", self.engine.gamma, minimum=1, maximum=3)


ORIGIN_RE = re.compile(r"https?://[A-Za-z0-9.\-\[\]:]+")


def parse_leds(text: str, led_count: int) -> list[int]:
    """``"120-140"``, ``"5"`` or ``"1-3,7,10-12"`` (inclusive) as sorted indices."""
    out: set[int] = set()
    for part in text.split(","):
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
        if not m:
            raise ValueError(f"{text!r}: expected ranges like 120-140 or 1-3,7,10-12")
        a = int(m[1])
        b = int(m[2]) if m[2] is not None else a
        if a > b:
            raise ValueError(f"{part.strip()!r}: range runs backwards")
        if b >= led_count:
            raise ValueError(f"{part.strip()!r}: LEDs go up to {led_count - 1}")
        out.update(range(a, b + 1))
    return sorted(out)


def find_config_path(explicit: str | Path | None = None) -> Path | None:
    """Pick the config file: explicit path, then $TREEMAP_CONFIG, then
    ./config.local.yaml (your own settings, kept out of git), then ./config.yaml (the
    documented defaults).

    An explicit or env path must exist; the others are optional (None if absent).
    """
    chosen = explicit or os.environ.get(CONFIG_ENV_VAR)
    if chosen:
        path = Path(chosen).expanduser()
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return path
    for path in (LOCAL_CONFIG_PATH, DEFAULT_CONFIG_PATH):
        if path.is_file():
            return path
    return None


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
        cfg = _build(Config, data, "", skip={"base_dir", "source", "device_dir", "led_count"},
                     file=where)
        cfg.validate()
    except ConfigError as e:
        raise ConfigError(f"{where}: {e}") from None
    return cfg


# Nested dataclass types for list/section fields, keyed by (owner class, field name).
_NESTED: dict[tuple[type, str], tuple[type, bool]] = {
    (Config, "scan"): (ScanConfig, False),
    (Config, "engine"): (EngineConfig, False),
    (Config, "server"): (ServerConfig, False),
}


def _build(cls: type, data: Any, where: str, skip: frozenset[str] | set[str] = frozenset(),
           file: str = "config") -> Any:
    label = where or "top level"
    if not isinstance(data, dict):
        raise ConfigError(f"{label}: expected a mapping, got {type(data).__name__}")
    assert is_dataclass(cls)
    known = {f.name: f for f in fields(cls) if f.name not in skip}
    retired = sorted(RETIRED.get(where, set()) & set(map(str, data)))
    if retired:
        log.warning("%s: ignoring %s: only the 1.x commands used %s, and they're gone. "
                    "Delete %s.", file, ", ".join(f"{where}.{k}" if where else k for k in retired),
                    "it" if len(retired) == 1 else "them",
                    "it" if len(retired) == 1 else "them")
        data = {k: v for k, v in data.items() if k not in retired}
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
            kwargs[name] = [_build(nested[0], v, f"{sub}[{i}]", file=file)
                            for i, v in enumerate(value)]
        else:
            kwargs[name] = _build(nested[0], value if value is not None else {}, sub, file=file)

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
