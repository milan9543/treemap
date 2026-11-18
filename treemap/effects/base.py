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
from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np

from treemap.patterns import parse_color

KINDS = ("color", "float", "int", "choice", "bool")


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
                return parse_color(str(value))
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
        }

    def _hint(self) -> str:
        if self.kind == "choice":
            return f" (one of {', '.join(self.choices)})"
        if self.kind == "color":
            return " (a name, #rrggbb or r,g,b)"
        return ""


@dataclass
class EffectContext:
    """What an effect knows about the tree."""

    n: int  # number of LEDs
    fps: float = 40.0  # nominal frame rate, for effects that step per frame
    positions: np.ndarray | None = None  # (n, 3) map, once position-aware effects arrive
    rng: np.random.Generator = field(default_factory=np.random.default_rng)


class Effect:
    name: ClassVar[str]
    label: ClassVar[str]
    group: ClassVar[str] = "Classic"
    description: ClassVar[str] = ""
    params: ClassVar[tuple[Param, ...]] = ()

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
            "params": [p.describe(n) for p in cls.params],
        }

    # -- helpers for subclasses -------------------------------------------------------

    def blank(self) -> np.ndarray:
        return np.zeros((self.n, 3), dtype=np.float32)

    def color(self, name: str) -> np.ndarray:
        return np.asarray(self.p[name], dtype=np.float32)


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
