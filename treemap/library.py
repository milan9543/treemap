"""Favourite effects and playlists, kept by the server in one JSON file.

A **favourite** is an effect with every parameter set::

    {"id": "3f9a1c2e", "name": "Gold plane", "effect": "plane", "params": {...}}

``params`` holds every parameter of the effect, as the engine reports them (colours as
``#rrggbb``), so the page can tell whether what's playing is a favourite.

A **playlist** plays favourites in turn, each for its own time, crossfading between them,
and starts again at the end (in a new order each time when shuffled)::

    {"id": "a71b0c55", "name": "Evening", "crossfade_s": 3, "shuffle": false,
     "items": [{"favourite": "3f9a1c2e", "duration_s": 300}, ...]}

Deleting a favourite takes it out of every playlist too.

A **palette** is a list of colours that effects can use, kept by id so that editing it
changes every favourite that uses it::

    {"id": "my-0c1d2e3f", "name": "Ice", "colors": ["#ffffff", "#78b4ff"]}

Deleting a palette puts the favourites that used it back on their effect's default.
The built-in palettes (:data:`treemap.effects.palettes.PRESETS`) can't be changed.

Favourites saved before version 2 had older colour settings; reading them carries those
over (:meth:`treemap.effects.Effect.upgrade`), and the next write saves them that way.

The file is read on every call and written whole (to a temporary file, then renamed), so
a half-written file is never read.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from treemap.effects import ParamError, get_effect
from treemap.effects import palettes as pal
from treemap.patterns import parse_color

VERSION = 2

MAX_NAME = 80
MAX_FAVOURITES = 500
MAX_PLAYLISTS = 100
MAX_ITEMS = 200
MAX_PALETTES = 100
DURATION_S = (5.0, 24 * 3600.0)  # how long one favourite plays in a playlist
CROSSFADE_S = (0.0, 30.0)
ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class LibraryError(ValueError):
    """A favourite or playlist that isn't valid."""


class Library:
    def __init__(self, path: Path, led_count: int | Callable[[], int]) -> None:
        self.path = path
        self._n = led_count if callable(led_count) else (lambda: led_count)
        self._lock = threading.Lock()
        self._palette_cache: tuple[Any, dict[str, list]] = (None, {})

    # -- favourites -------------------------------------------------------------------

    def favourites(self) -> list[dict[str, Any]]:
        return self._read()["favourites"]

    def favourite(self, fav_id: str) -> dict[str, Any]:
        """Raises KeyError."""
        return _find(self.favourites(), fav_id, "favourite")

    def add_favourite(self, body: dict[str, Any]) -> dict[str, Any]:
        """``{"name", "effect", "params", "id"?}``: ``id`` lets a page that keeps a copy
        of the list name the new one itself."""
        _only(body, {"id", "name", "effect", "params"})
        with self._lock:
            data = self._read()
            favs = data["favourites"]
            if len(favs) >= MAX_FAVOURITES:
                raise LibraryError(f"there are already {MAX_FAVOURITES} favourites")
            effect, params = self._effect_params(body.get("effect"), body.get("params") or {})
            fav = {"id": _new_id(body.get("id"), favs), "name": _name(body.get("name")),
                   "effect": effect, "params": params}
            favs.append(fav)
            self._write(data)
        return fav

    def update_favourite(self, fav_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """``{"name"?, "params"?}``: rename it, or replace its settings. Raises KeyError."""
        _only(body, {"name", "params"})
        with self._lock:
            data = self._read()
            fav = _find(data["favourites"], fav_id, "favourite")
            if "name" in body:
                fav["name"] = _name(body["name"])
            if "params" in body:
                fav["params"] = self._effect_params(fav["effect"], body["params"])[1]
            self._write(data)
        return fav

    def remove_favourite(self, fav_id: str) -> None:
        """Delete it, and take it out of every playlist. Raises KeyError."""
        with self._lock:
            data = self._read()
            fav = _find(data["favourites"], fav_id, "favourite")
            data["favourites"].remove(fav)
            for pl in data["playlists"]:
                pl["items"] = [i for i in pl["items"] if i["favourite"] != fav_id]
            self._write(data)

    def playlists(self) -> list[dict[str, Any]]:
        return self._read()["playlists"]

    # -- palettes ---------------------------------------------------------------------

    def palettes(self) -> list[dict[str, Any]]:
        """The built-in palettes (``"preset": true``), then the custom ones."""
        return pal.describe_presets() + [{**p, "preset": False} for p in self._read()["palettes"]]

    def palette_colors(self, pal_id: str) -> list[tuple[int, int, int]] | None:
        """A custom palette's colours, or None. Effects call this every frame, so the
        file is only read again when it changes."""
        try:
            st = self.path.stat()
            key = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            key = None
        if key != self._palette_cache[0]:
            found = {p["id"]: [parse_color(c) for c in p["colors"]]
                     for p in self._read()["palettes"]}
            self._palette_cache = (key, found)
        return self._palette_cache[1].get(pal_id)

    def add_palette(self, body: dict[str, Any]) -> dict[str, Any]:
        """``{"name", "colors"}``."""
        with self._lock:
            data = self._read()
            if len(data["palettes"]) >= MAX_PALETTES:
                raise LibraryError(f"there are already {MAX_PALETTES} palettes")
            taken = {p["id"] for p in data["palettes"]}
            while (new := f"my-{secrets.token_hex(4)}") in taken:
                pass
            palette = {"id": new, **self._palette_fields(body)}
            data["palettes"].append(palette)
            self._write(data)
        return {**palette, "preset": False}

    def put_palette(self, pal_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Replace its name and colours. Raises KeyError."""
        with self._lock:
            data = self._read()
            palette = _find(data["palettes"], pal_id, "palette")
            palette.update(self._palette_fields(body))
            self._write(data)
        return {**palette, "preset": False}

    def remove_palette(self, pal_id: str) -> None:
        """Delete it; favourites that used it go back to their effect's default. Raises
        KeyError."""
        with self._lock:
            data = self._read()
            data["palettes"].remove(_find(data["palettes"], pal_id, "palette"))
            for fav in data["favourites"]:
                try:
                    params = get_effect(fav["effect"]).params
                except KeyError:
                    continue
                for p in params:
                    if p.kind == "palette" and fav["params"].get(p.name) == pal_id:
                        fav["params"][p.name] = p.default
            self._write(data)

    @staticmethod
    def _palette_fields(body: dict[str, Any]) -> dict[str, Any]:
        _only(body, {"name", "colors"})
        colors = body.get("colors")
        if not isinstance(colors, list) or not 1 <= len(colors) <= pal.MAX_COLORS:
            raise LibraryError(f"colors must be a list of 1-{pal.MAX_COLORS} colours")
        try:
            rgb = [parse_color(c) for c in colors if isinstance(c, str)]
        except ValueError as e:
            raise LibraryError(str(e)) from None
        if len(rgb) != len(colors):
            raise LibraryError("each colour is text: #rrggbb")
        return {"name": _name(body.get("name")), "colors": [pal.to_hex(c) for c in rgb]}

    def playlist(self, pl_id: str) -> dict[str, Any]:
        """Raises KeyError."""
        return _find(self.playlists(), pl_id, "playlist")

    def add_playlist(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            if len(data["playlists"]) >= MAX_PLAYLISTS:
                raise LibraryError(f"there are already {MAX_PLAYLISTS} playlists")
            pl = {"id": _new_id(None, data["playlists"]), **self._playlist_fields(body, data)}
            data["playlists"].append(pl)
            self._write(data)
        return pl

    def put_playlist(self, pl_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Replace its name, items, crossfade and shuffle. Raises KeyError."""
        with self._lock:
            data = self._read()
            pl = _find(data["playlists"], pl_id, "playlist")
            pl.update(self._playlist_fields(body, data))
            self._write(data)
        return pl

    def remove_playlist(self, pl_id: str) -> None:
        """Raises KeyError."""
        with self._lock:
            data = self._read()
            data["playlists"].remove(_find(data["playlists"], pl_id, "playlist"))
            self._write(data)

    # -- checks -----------------------------------------------------------------------

    def _effect_params(self, effect: Any, params: Any) -> tuple[str, dict]:
        if not isinstance(effect, str):
            raise LibraryError("effect must be an effect's name")
        if not isinstance(params, dict):
            raise LibraryError("params must be an object")
        try:
            return effect, get_effect(effect).check_params(params, self._n())
        except KeyError as e:
            raise LibraryError(e.args[0]) from None
        except ParamError as e:
            raise LibraryError(str(e)) from None

    @staticmethod
    def _playlist_fields(body: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        _only(body, {"name", "items", "crossfade_s", "shuffle"})
        items = body.get("items", [])
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise LibraryError(f"items must be a list of up to {MAX_ITEMS} favourites")
        known = {f["id"] for f in data["favourites"]}
        out = []
        for item in items:
            if not isinstance(item, dict) or set(item) - {"favourite", "duration_s"}:
                raise LibraryError('each item is {"favourite": id, "duration_s": seconds}')
            if item.get("favourite") not in known:
                raise LibraryError(f"there's no favourite {item.get('favourite')!r}")
            out.append({"favourite": item["favourite"],
                        "duration_s": _number(item.get("duration_s", 300), "duration_s", DURATION_S)})
        shuffle = body.get("shuffle", False)
        if not isinstance(shuffle, bool):
            raise LibraryError("shuffle must be true or false")
        return {"name": _name(body.get("name")), "items": out,
                "crossfade_s": _number(body.get("crossfade_s", 3), "crossfade_s", CROSSFADE_S),
                "shuffle": shuffle}

    # -- the file ---------------------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError) as e:
            raise OSError(f"can't read {self.path}: {e}") from None
        old = data.get("version", VERSION) < VERSION
        return {"favourites": [self._upgrade(f, old) for f in data.get("favourites") or []],
                "playlists": list(data.get("playlists") or []),
                "palettes": list(data.get("palettes") or [])}

    def _upgrade(self, fav: dict[str, Any], old: bool) -> dict[str, Any]:
        """A favourite with every setting its effect has now, for favourites saved by an
        older version or before the effect gained settings."""
        try:
            cls = get_effect(fav["effect"])
        except KeyError:
            return fav  # an effect that's gone: it can't play, but keep it
        n = self._n()
        return {**fav, "params": cls.check_params(cls.upgrade(fav["params"], n, old), n)}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"version": VERSION, **data}, indent=1) + "\n")
        os.replace(tmp, self.path)


def _only(body: Any, allowed: set[str]) -> None:
    if not isinstance(body, dict):
        raise LibraryError("send a JSON object")
    unknown = set(body) - allowed
    if unknown:
        raise LibraryError(f"unknown field(s): {', '.join(sorted(unknown))}")


def _find(items: list[dict[str, Any]], item_id: str, what: str) -> dict[str, Any]:
    for item in items:
        if item["id"] == item_id:
            return item
    raise KeyError(f"there's no {what} {item_id!r}")


def _new_id(wanted: Any, items: list[dict[str, Any]]) -> str:
    taken = {i["id"] for i in items}
    if wanted is not None:
        if not isinstance(wanted, str) or not ID.fullmatch(wanted):
            raise LibraryError("id must be 1-64 letters, digits, - or _")
        if wanted in taken:
            raise LibraryError(f"id {wanted!r} is taken")
        return wanted
    while (new := secrets.token_hex(4)) in taken:
        pass
    return new


def _name(value: Any, default: str | None = None) -> str:
    name = value.strip() if isinstance(value, str) else ""
    if not name and default:
        name = default
    if not name or len(name) > MAX_NAME:
        raise LibraryError(f"name must be 1-{MAX_NAME} characters")
    return name


def _number(value: Any, what: str, bounds: tuple[float, float]) -> float:
    lo, hi = bounds
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise LibraryError(f"{what} must be a number {lo:g}-{hi:g}")
    return float(value)
