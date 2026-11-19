"""Effects: importing this package registers every built-in effect."""

# Registration order is the order the viewer and `treemap effects` list them in.
from treemap.effects import spatial, classic, diagnostics, mapping  # noqa: F401, I001
from treemap.effects.base import Effect, EffectContext, MapEffect, Param, ParamError
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
    "MapEffect",
    "Param",
    "ParamError",
    "create_effect",
    "describe_effects",
    "effect_names",
    "get_effect",
    "register",
]
