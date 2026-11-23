"""Effect and parameter base classes.

An effect renders one frame at a time: ``render(t)`` returns an ``(N, 3)`` array of RGB
values 0-255 (any numeric dtype; the engine clips, scales and converts). Effects declare
their parameters as :class:`Param` objects, which gives validation, CLI parsing
(``--param k=v``) and the controls the browser builds, all from one definition.
Parameters can change while an effect runs, so ``render`` should read ``self.p`` each
frame rather than caching values in ``setup``.
"""

from __future__ import annotations

import colorsys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np

from treemap.effects import palettes
from treemap.effects.palettes import XMAS
from treemap.mapping.model import TreeMap
from treemap.patterns import parse_color

KINDS = ("color", "float", "int", "choice", "bool", "palette")

WARM_WHITE = (255, 150, 60)


class ParamError(ValueError):
    """An unknown parameter or an invalid parameter value."""


@dataclass(frozen=True)
class Param:
    name: str
    kind: str
    default: Any
    label: str = ""
    help: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: tuple[str, ...] = ()
    max_is_last_led: bool = False  # int params naming an LED: max becomes led_count - 1
    group: str = ""  # params sharing a group are shown together: colours, background, sparkle
    # shown only while each named param has one of the listed values
    when: tuple[tuple[str, tuple[Any, ...]], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown param kind {self.kind!r}")

    def bounds(self, n: int) -> tuple[float | None, float | None]:
        return self.min, (n - 1 if self.max_is_last_led else self.max)

    def parse(self, value: Any, n: int) -> Any:
        """Validate a value from JSON or a CLI string; return the effect's native type."""
        try:
            if self.kind == "color":
                if isinstance(value, (list, tuple)) and len(value) == 3:
                    rgb = tuple(int(c) for c in value)
                    if all(0 <= c <= 255 for c in rgb):
                        return rgb
                    raise ValueError
                name = str(value).strip().lower()
                return XMAS[name] if name in XMAS else parse_color(name)
            if self.kind == "palette":
                if not palettes.is_palette_id(value):
                    raise ValueError
                return value
            if self.kind == "bool":
                if isinstance(value, bool):
                    return value
                s = str(value).strip().lower()
                if s in ("1", "true", "yes", "on"):
                    return True
                if s in ("0", "false", "no", "off"):
                    return False
                raise ValueError
            if self.kind == "choice":
                if value not in self.choices:
                    raise ValueError
                return value
            if isinstance(value, bool):
                raise ValueError
            number = float(value)
            if self.kind == "int":
                if not number.is_integer():
                    raise ValueError
                number = int(number)
        except (TypeError, ValueError):
            raise ParamError(f"{self.name}: invalid {self.kind} {value!r}{self._hint()}") from None
        lo, hi = self.bounds(n)
        if (lo is not None and number < lo) or (hi is not None and number > hi):
            raise ParamError(f"{self.name}: {number:g} is outside {lo:g}-{hi:g}")
        return number

    def to_json(self, value: Any) -> Any:
        if self.kind == "color":
            return "#{:02x}{:02x}{:02x}".format(*value)
        return value

    def describe(self, n: int) -> dict[str, Any]:
        lo, hi = self.bounds(n)
        return {
            "name": self.name,
            "kind": self.kind,
            "default": self.to_json(self.default),
            "label": self.label or self.name.replace("_", " ").capitalize(),
            "help": self.help,
            "min": lo,
            "max": hi,
            "step": self.step,
            "choices": list(self.choices),
            "group": self.group,
            "when": [{"param": name, "values": list(values)} for name, values in self.when],
        }

    def _hint(self) -> str:
        if self.kind == "choice":
            return f" (one of {', '.join(self.choices)})"
        if self.kind == "color":
            return " (a name, #rrggbb or r,g,b)"
        if self.kind == "palette":
            return " (a palette's id)"
        return ""


def color_params(color: tuple[int, int, int], palette: str = "christmas", *,
                 colors: str = "one", palette_help: str = "") -> tuple[Param, Param, Param]:
    """One colour, or colours from a palette: what each effect does with the palette's
    colours is up to it (``palette_help`` says)."""
    return (
        Param("colors", "choice", colors, choices=("one", "palette"), label="Colours",
              group="colours", help="one colour, or the colours of a palette"),
        Param("color", "color", color, label="Colour", group="colours",
              when=(("colors", ("one",)),)),
        Param("palette", "palette", palette, group="colours", help=palette_help,
              when=(("colors", ("palette",)),)),
    )


@dataclass
class EffectContext:
    """What an effect knows about the tree."""

    n: int  # number of LEDs
    fps: float = 40.0  # nominal frame rate, for effects that step per frame
    rng: np.random.Generator = field(default_factory=np.random.default_rng)
    # Returns the current tree map (or None); usually a treemap.mapping.model.MapFile,
    # which reloads the map when a scan changes it.
    tree_map: Callable[[], TreeMap | None] | None = None
    # A custom palette's colours by its id (None if there's no such palette).
    palettes: Callable[[str], list[tuple[int, int, int]] | None] | None = None


class Effect:
    name: ClassVar[str]
    label: ClassVar[str]
    group: ClassVar[str] = "Classic"
    description: ClassVar[str] = ""
    params: ClassVar[tuple[Param, ...]] = ()
    needs_map: ClassVar[bool] = False  # it places light by the LEDs' mapped positions

    def __init__(self, ctx: EffectContext, **params: Any) -> None:
        self.ctx = ctx
        self.n = ctx.n
        self.rng = ctx.rng
        self.p: dict[str, Any] = {p.name: p.default for p in self.params}
        self.set_params(params)
        self.setup()

    def setup(self) -> None:
        """Allocate state. Called once, after the initial parameters are set."""

    def render(self, t: float) -> np.ndarray:
        """The frame at ``t`` seconds since the effect started: ``(n, 3)`` values 0-255."""
        raise NotImplementedError

    def set_params(self, values: dict[str, Any]) -> None:
        """Validate all values first, then apply, so a bad value changes nothing."""
        by_name = {p.name: p for p in self.params}
        parsed = {}
        for key, value in values.items():
            if key not in by_name:
                known = ", ".join(by_name) or "none"
                raise ParamError(f"{self.name} has no parameter {key!r} (parameters: {known})")
            parsed[key] = by_name[key].parse(value, self.n)
        self.p.update(parsed)

    def param_values(self) -> dict[str, Any]:
        return {p.name: p.to_json(self.p[p.name]) for p in self.params}

    @classmethod
    def describe(cls, n: int) -> dict[str, Any]:
        return {
            "name": cls.name,
            "label": cls.label,
            "group": cls.group,
            "description": cls.description,
            "needs_map": cls.needs_map,
            "params": [p.describe(n) for p in cls.params],
        }

    @classmethod
    def check_params(cls, values: dict[str, Any], n: int) -> dict[str, Any]:
        """Every parameter's value as JSON (``values`` checked, defaults for the rest),
        without starting the effect. Raises ParamError."""
        by_name = {p.name: p for p in cls.params}
        out = {p.name: p.to_json(p.default) for p in cls.params}
        for key, value in values.items():
            if key not in by_name:
                raise ParamError(f"{cls.name} has no parameter {key!r} "
                                 f"(parameters: {', '.join(by_name) or 'none'})")
            out[key] = by_name[key].to_json(by_name[key].parse(value, n))
        return out

    @classmethod
    def upgrade(cls, values: dict[str, Any], n: int, old: bool = False) -> dict[str, Any]:
        """Saved settings (a favourite's) as this version takes them: ones it no longer
        has or can't read are dropped, so they play with their defaults. ``old``: saved
        before the colour settings changed, so carry the renamed ones over (:meth:`legacy`)."""
        by_name = {p.name: p for p in cls.params}
        out = {}
        for key, value in (cls.legacy(dict(values)) if old else values).items():
            if key in by_name:
                try:
                    out[key] = by_name[key].to_json(by_name[key].parse(value, n))
                except ParamError:
                    pass
        return out

    @classmethod
    def legacy(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Old settings carried over to new ones; effects whose settings changed add theirs."""
        return values

    # -- helpers for subclasses -------------------------------------------------------

    def blank(self) -> np.ndarray:
        return np.zeros((self.n, 3), dtype=np.float32)

    def color(self, name: str) -> np.ndarray:
        return np.asarray(self.p[name], dtype=np.float32)

    def palette(self, name: str = "palette") -> np.ndarray:
        """The colours of the palette a palette parameter names, ``(k, 3)``; a palette
        that's gone (deleted) gives the parameter's default."""
        pid = self.p[name]
        colors = palettes.preset(pid)
        if colors is None and self.ctx.palettes is not None:
            custom = self.ctx.palettes(pid)
            colors = palettes.stops(custom) if custom else None
        if colors is None:
            default = next(p.default for p in self.params if p.name == name)
            colors = palettes.preset(default)
        return colors if colors is not None else palettes.preset("christmas")

    def colors(self, k: int | np.ndarray) -> np.ndarray:
        """For effects with :func:`color_params`: the colour of the ``k``-th thing (pass,
        ring, arm...), ``k.shape + (3,)``: the one colour, or round the palette."""
        if self.p["colors"] == "one":
            return np.broadcast_to(self.color("color"), np.shape(k) + (3,)).astype(np.float32)
        return palettes.pick(self.palette(), k)


class MapEffect(Effect):
    """An effect that needs the LED positions. Starting one without a map is a
    ParamError; if the map goes away while it runs, it renders black."""

    needs_map = True

    def setup(self) -> None:
        if self.tree_map() is None:
            raise ParamError("no map yet: scan first")

    def tree_map(self) -> TreeMap | None:
        """The current map (reloaded if it changed on disk), if it fits these LEDs."""
        load = self.ctx.tree_map
        m = load() if load is not None else None
        if m is not None and m.led_count != self.n:
            raise ParamError(f"the tree map has {m.led_count} LEDs but the tree has {self.n}")
        return m

    def render(self, t: float) -> np.ndarray:
        m = self.tree_map()
        if m is None or not m.geometry.valid.any():
            return self.blank()
        frame = self.render_map(t, m)
        return np.where(m.geometry.valid[:, None], frame, 0.0)

    def render_map(self, t: float, m: TreeMap) -> np.ndarray:
        """The frame at ``t`` for map ``m``; LEDs without a position are blacked out."""
        raise NotImplementedError


def hsv_to_rgb(h: np.ndarray, s: np.ndarray | float = 1.0, v: np.ndarray | float = 1.0) -> np.ndarray:
    """Vectorised HSV (all 0-1, hue wraps) to RGB 0-255, shape ``h.shape + (3,)``."""
    h = np.mod(np.asarray(h, dtype=np.float32), 1.0)
    s = np.broadcast_to(np.asarray(s, dtype=np.float32), h.shape)
    v = np.broadcast_to(np.asarray(v, dtype=np.float32), h.shape)
    k = np.stack([(5 + h * 6) % 6, (3 + h * 6) % 6, (1 + h * 6) % 6], axis=-1)
    rgb = v[..., None] - v[..., None] * s[..., None] * np.clip(np.minimum(k, 4 - k), 0, 1)
    return rgb * 255.0


def rgb_hue(rgb: tuple[int, int, int]) -> float:
    return colorsys.rgb_to_hsv(*(c / 255 for c in rgb))[0]
