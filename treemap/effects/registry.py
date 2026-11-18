"""Effect registry: name -> Effect class."""

from __future__ import annotations

from typing import Any

from treemap.effects.base import Effect, EffectContext

_EFFECTS: dict[str, type[Effect]] = {}


def register(cls: type[Effect]) -> type[Effect]:
    """Class decorator adding an effect to the registry."""
    if cls.name in _EFFECTS:
        raise ValueError(f"effect {cls.name!r} registered twice")
    _EFFECTS[cls.name] = cls
    return cls


def effect_names() -> list[str]:
    return list(_EFFECTS)


def get_effect(name: str) -> type[Effect]:
    try:
        return _EFFECTS[name]
    except KeyError:
        raise KeyError(f"unknown effect {name!r}; available: {', '.join(_EFFECTS)}") from None


def create_effect(name: str, ctx: EffectContext, params: dict[str, Any] | None = None) -> Effect:
    return get_effect(name)(ctx, **(params or {}))


def describe_effects(n: int) -> list[dict[str, Any]]:
    return [cls.describe(n) for cls in _EFFECTS.values()]
