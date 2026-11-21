"""Loading and validating ``config.yaml``.

Every key is optional. Missing keys fall back to the dataclass defaults, unknown keys are
rejected (so a typo doesn't silently do nothing), and values are validated on load.

The number of LEDs isn't a key: it's :attr:`Config.led_count`, taken from the simulated
tree (``output: sim``) or from the controllers (``output: wled``).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import MISSING, asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")
LOCAL_CONFIG_PATH = Path("config.local.yaml")  # your own settings, not in git
CONFIG_ENV_VAR = "TREEMAP_CONFIG"

OUTPUT_TYPES = ("sim", "wled")
SHAPES = ("tree", "flat")
CAMERA_TYPES = ("sim", "android")
MAX_LEDS = 5000  # the most LEDs anything here handles (also the sim generator's limit)
REMOVED_KEYS = {
    "led_count": "led_count is no longer set in the config: the simulator takes it from "
                 "the simulated tree (the viewer's Tree step or sim.strips), WLED from "
                 "the controllers. Delete the line.",
}


class ConfigError(ValueError):
    """Raised when the config file is missing required structure or has invalid values."""


@dataclass
class Controller:
    """One WLED controller owning global LEDs ``[start, start + count)``.

    Only ``host`` is required: ``start`` defaults to where the previous controller's LEDs
    end (0 for the first), and ``count`` to the LED count set in WLED itself, read from
    the controller (see :meth:`Config.controller_layout`).
    """

    host: str
    start: int | None = None
    count: int | None = None
    reverse: bool = False


@dataclass
class CameraConfig:
    type: str = "sim"  # sim: the viewer's virtual phone; android: IP Webcam
    url: str | None = None
    fov_deg: float = 65.0  # horizontal field of view, a starting guess the solve refines


@dataclass
class ScanConfig:
    profile: str = "default"
    symbol_ms: int = 150  # how long each colour of the code shows
    brightness: int = 160  # 0-255 while flashing; lower keeps a real camera from clipping
    round_s: float = 12.0  # seconds of flashing per round
    status_s: float = 4.0  # seconds of status colours between rounds
    max_rounds: int = 10  # stop after this many rounds (or when every LED is ok)
    camera_fps: float = 24.0  # frames per second the viewer's virtual phone sends
    countdown_s: float = 5.0  # seconds to point the camera at the LEDs before a scan


@dataclass
class EngineConfig:
    fps: float = 40.0
    brightness: float = 0.8
    crossfade: float = 0.6  # seconds
    gamma: float | None = None  # None: see Config.gamma


@dataclass
class StripConfig:
    """One strip on the simulated tree (see ``treemap.sim.tree.StripSpec``)."""

    leds: int
    length: float | None = None
    start: str = "auto"


@dataclass
class SimConfig:
    seed: int | None = None
    strips: list[StripConfig] | None = None  # None = two strips of 200
    height: float | None = None
    radius: float | None = None
    layout: str = "auto"
    quirks: bool = True
    hidden_leds: str | None = None  # e.g. "57, 120-127": never seen by the virtual phone
    tree_file: str = "data/sim_tree.json"
    host: str = "127.0.0.1"
    port: int = 8765


SCAN_PAGE = "https://treemap-scan.pages.dev"  # the hosted scan page (scanapp/)
DEFAULT_ORIGINS = (SCAN_PAGE, "https://treemap-spike.pages.dev", "http://localhost:5173")


@dataclass
class ServerConfig:
    """``treemap serve``: the HTTP API the phone's page talks to."""

    host: str = "0.0.0.0"  # every network interface, so the phone can reach it
    port: int = 8765
    # Web pages allowed to use the API from a browser (CORS). "*" allows any.
    origins: list[str] = field(default_factory=lambda: list(DEFAULT_ORIGINS))


@dataclass
class Config:
    # tree: LEDs wound round a tree, mapped in 3D. flat: LEDs laid on the floor (or on a
    # wall), mapped in 2D.
    shape: str = "tree"
    output: str = "sim"
    controllers: list[Controller] = field(
        default_factory=lambda: [Controller(host="wled-tree.local")]
    )
    camera: CameraConfig = field(default_factory=CameraConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    sim: SimConfig = field(default_factory=SimConfig)

    # Not a config key: directory relative paths are resolved against.
    base_dir: Path = field(default_factory=Path.cwd, repr=False, compare=False)
    # Not a config key: the file this was loaded from, if any.
    source: Path | None = field(default=None, repr=False, compare=False)
    # Not a config key: the simulated tree's LED count, keyed by its file's mtime and size.
    _tree_count: tuple[Any, int] | None = field(default=None, init=False, repr=False,
                                                compare=False)
    # Not a config key: the controllers with every start and count filled in.
    _layout: list[Controller] | None = field(default=None, init=False, repr=False,
                                             compare=False)

    def controller_layout(self) -> list[Controller]:
        """The controllers with ``start`` and ``count`` filled in: a missing count is
        read from the controller's WLED (once, then kept), a missing start is where the
        previous controller ends. Raises :class:`ConfigError` if a controller whose count
        is needed can't be reached, or the LEDs overlap or leave a gap."""
        if self._layout is None:
            self._layout = layout_controllers(self.controllers, self.output, _wled_led_count)
        return self._layout

    @property
    def led_count(self) -> int:
        """How many LEDs there are: in the simulator the simulated tree's (re-read when
        the tree file changes, so a tree generated in the viewer counts at once), else
        where the last controller's LEDs end."""
        if self.output == "wled":
            return max((c.start + c.count for c in self.controller_layout()), default=0)
        path = self.sim_tree_path
        try:
            st = path.stat()
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = None
        if stamp is not None:
            if self._tree_count is not None and self._tree_count[0] == stamp:
                return self._tree_count[1]
            try:
                n = int(json.loads(path.read_text())["led_count"])
            except (OSError, ValueError, KeyError, TypeError):
                n = 0
            if n > 0:
                self._tree_count = (stamp, n)
                return n
        # no tree yet: the one `treemap sim new` (or the viewer) would generate
        from treemap.sim.tree import spec_from_config  # lazy: pulls in numpy

        return spec_from_config(self).led_count

    def resolve(self, path: str | Path) -> Path:
        """Resolve a path from the config relative to the config file's directory."""
        p = Path(path).expanduser()
        return p if p.is_absolute() else self.base_dir / p

    @property
    def scan_dir(self) -> Path:
        return self.resolve(Path("data") / "scans" / self.scan.profile)

    @property
    def colours_path(self) -> Path:
        """The camera's measured colours, written by ``treemap camera check``."""
        return self.resolve(Path("data") / "camera_colours.json")

    @property
    def camera_id(self) -> str:
        """Which camera measured colours belong to."""
        return self.camera.type if self.camera.type == "sim" else f"{self.camera.type} {self.camera.url}"

    @property
    def map_path(self) -> Path:
        """The reconstructed map written by ``treemap reconstruct``."""
        return self.resolve(Path("data") / "tree_map.json")

    @property
    def gamma(self) -> float:
        """engine.gamma, or by default 1 in the simulator (the screen already applies a
        gamma curve) and 2.2 on real LEDs, which are linear."""
        if self.engine.gamma is not None:
            return float(self.engine.gamma)
        return 2.2 if self.output == "wled" else 1.0

    @property
    def sim_tree_path(self) -> Path:
        return self.resolve(self.sim.tree_file)

    @property
    def sim_hidden_leds(self) -> list[int]:
        """sim.hidden_leds that exist on the current tree."""
        if not self.sim.hidden_leds:
            return []
        n = self.led_count
        return [i for i in parse_leds(str(self.sim.hidden_leds), MAX_LEDS) if i < n]

    def to_dict(self) -> dict[str, Any]:
        """The config as plain data, without the non-key fields."""
        d = asdict(self)
        for key in ("base_dir", "source", "_tree_count", "_layout"):
            d.pop(key)
        return d

    def validate(self) -> None:
        _check_choice("shape", self.shape, SHAPES)
        _check_choice("output", self.output, OUTPUT_TYPES)

        for i, c in enumerate(self.controllers):
            where = f"controllers[{i}]"
            if not isinstance(c.host, str) or not c.host:
                raise ConfigError(f"{where}.host must be a non-empty string")
            if c.start is not None:
                _check_int(f"{where}.start", c.start, minimum=0)
            if c.count is not None:
                _check_int(f"{where}.count", c.count, minimum=1)
            _check_bool(f"{where}.reverse", c.reverse)
        if self.output == "wled" and not self.controllers:
            raise ConfigError("output: wled needs at least one entry in controllers")
        if all(c.count is not None for c in self.controllers):
            # Everything is known without asking WLED: check the layout now.
            self._layout = layout_controllers(self.controllers, self.output, None)

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

        _check_choice("camera.type", self.camera.type, CAMERA_TYPES)
        if self.camera.url is not None and not isinstance(self.camera.url, str):
            raise ConfigError("camera.url must be a string or null")
        if self.camera.type == "android" and not self.camera.url:
            raise ConfigError("camera.type: android needs camera.url (e.g. http://phone:8080)")

        s = self.scan
        if not isinstance(s.profile, str) or not s.profile or "/" in s.profile:
            raise ConfigError("scan.profile must be a non-empty name without '/'")
        _check_int("scan.symbol_ms", s.symbol_ms, minimum=40, maximum=2000)
        _check_int("scan.brightness", s.brightness, minimum=1, maximum=255)
        _check_number("scan.round_s", s.round_s, minimum=2, maximum=600)
        _check_number("scan.status_s", s.status_s, minimum=0, maximum=60)
        _check_int("scan.max_rounds", s.max_rounds, minimum=1)
        _check_number("scan.camera_fps", s.camera_fps, minimum=5, maximum=60)
        _check_number("scan.countdown_s", s.countdown_s, minimum=0, maximum=60)
        _check_number("camera.fov_deg", self.camera.fov_deg, minimum=20, maximum=150)

        _check_number("engine.fps", self.engine.fps, minimum=1, maximum=120)
        _check_number("engine.brightness", self.engine.brightness, minimum=0, maximum=1)
        _check_number("engine.crossfade", self.engine.crossfade, minimum=0, maximum=10)
        if self.engine.gamma is not None:
            _check_number("engine.gamma", self.engine.gamma, minimum=1, maximum=3)

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
        if sim.hidden_leds is not None:
            try:
                parse_leds(str(sim.hidden_leds), MAX_LEDS)
            except ValueError as e:
                raise ConfigError(f"sim.hidden_leds: {e}") from None
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


ORIGIN_RE = re.compile(r"https?://[A-Za-z0-9.\-\[\]:]+")


def layout_controllers(controllers: list[Controller], output: str, count_of) -> list[Controller]:
    """Fill in each controller's ``start`` (where the previous one ends) and ``count``
    (``count_of(index, controller)``, for ones that don't set it), then check the LEDs
    don't overlap and, with ``output: wled``, cover 0..N-1 without a gap."""
    out: list[Controller] = []
    end = 0
    for i, c in enumerate(controllers):
        start = c.start if c.start is not None else end
        count = c.count if c.count is not None else count_of(i, c)
        out.append(Controller(c.host, start, count, c.reverse))
        end = start + count
    ranges = sorted((c.start, c.start + c.count, i) for i, c in enumerate(out))
    for (_, end_a, ia), (start_b, _, ib) in zip(ranges, ranges[1:]):
        if start_b < end_a:
            raise ConfigError(f"controllers[{ia}] and controllers[{ib}] overlap")
    if output == "wled":
        # the controllers define the LEDs, so between them they must cover 0..N-1
        end = 0
        for start, stop, i in ranges:
            if start > end:
                raise ConfigError(
                    f"no controller drives LEDs {end}-{start - 1}; "
                    f"controllers[{i}] starts at {start}"
                )
            end = stop
        if end > MAX_LEDS:
            raise ConfigError(f"the controllers drive {end} LEDs; at most {MAX_LEDS}")
    return out


def _wled_led_count(index: int, c: Controller) -> int:
    """The LED count set in a controller's WLED."""
    from treemap.outputs.base import OutputError
    from treemap.outputs.wled import fetch_state

    try:
        count = fetch_state(c.host)["info"].get("leds", {}).get("count")
    except OutputError as e:
        raise ConfigError(f"controllers[{index}] has no count, so it's read from WLED, but "
                          f"{str(e).rstrip('.?')}. Set controllers[{index}].count to go on "
                          "without it.") from None
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ConfigError(f"controllers[{index}]: WLED at {c.host} reports no LED count; "
                          "set its LED count in WLED's LED Preferences, or count in the config")
    return count


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
        cfg = _build(Config, data, "", skip={"base_dir", "source", "_tree_count", "_layout"})
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
    (Config, "server"): (ServerConfig, False),
    (Config, "sim"): (SimConfig, False),
    (SimConfig, "strips"): (StripConfig, True),
}


def _build(cls: type, data: Any, where: str, skip: frozenset[str] | set[str] = frozenset()) -> Any:
    label = where or "top level"
    if not isinstance(data, dict):
        raise ConfigError(f"{label}: expected a mapping, got {type(data).__name__}")
    assert is_dataclass(cls)
    known = {f.name: f for f in fields(cls) if f.name not in skip}
    if cls is Config:
        for key, why in REMOVED_KEYS.items():
            if key in data:
                raise ConfigError(why)
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
