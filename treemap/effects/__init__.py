"""Effects: importing this package registers every built-in effect."""

from treemap.effects import classic, diagnostics, mapping  # noqa: F401  (registers them)
from treemap.effects.base import Effect, EffectContext, Param, ParamError
from treemap.effects.registry import (
    create_effect,
    describe_effects,
    effect_names,
    get_effect,
    register,
)

__all__ = [
    "Effect",
    "EffectContext",
    "Param",
    "ParamError",
    "create_effect",
    "describe_effects",
    "effect_names",
    "get_effect",
    "register",
]
