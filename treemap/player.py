"""What the effects engine plays: an effect, a favourite, or a playlist of favourites.

A playlist runs on a thread of its own: it starts each favourite with the playlist's
crossfade, waits its time, then moves on, round and round until something else is played
or it's stopped. A favourite that can't play (deleted, or a 3D effect with no map) is
skipped; a playlist none of whose favourites can play stops.

Every change goes through one lock, and the playlist's thread waits under that lock (on a
condition: a skip or a stop wakes it) and checks it's still wanted before it starts the
next favourite, so it never overrides what the user picked after it.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any

from treemap.effects import ParamError
from treemap.engine import Engine
from treemap.library import Library

log = logging.getLogger(__name__)


class Player:
    def __init__(self, engine: Engine, library: Library) -> None:
        self.engine = engine
        self.library = library
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)  # the playlist's thread waits on it
        self._favourite: str | None = None  # the favourite last started, if any
        self._playlist: dict[str, Any] | None = None  # the playlist playing, as it was started
        self._stop = threading.Event()  # the current playlist's
        self._order: list[int] = []
        self._pos = -1  # in _order: the item playing
        self._ends = 0.0  # when it moves on (monotonic)
        self._skipped: str | None = None  # why the last favourite skipped didn't play

    # -- control ----------------------------------------------------------------------

    def play_effect(self, name: str, params: dict[str, Any] | None = None) -> None:
        """Raises KeyError, ParamError."""
        with self._lock:
            self.engine.start(name, params)
            self._end_playlist()
            self._favourite = None

    def play_favourite(self, fav_id: str) -> None:
        """Raises KeyError (no such favourite or effect), ParamError."""
        with self._lock:
            fav = self.library.favourite(fav_id)
            self.engine.start(fav["effect"], fav["params"])
            self._end_playlist()
            self._favourite = fav_id

    def play_playlist(self, pl_id: str) -> None:
        """Start a playlist at its first favourite (or a random one, shuffled). Raises
        KeyError, or ParamError when none of its favourites can play."""
        with self._lock:
            pl = self.library.playlist(pl_id)
            if not pl["items"]:
                raise ParamError(f"{pl['name']} has no favourites in it yet")
            self._end_playlist()
            self._playlist, self._order, self._pos = pl, [], -1
            stop = self._stop = threading.Event()
            if not self._next():
                self._playlist = None
                raise ParamError(f"none of {pl['name']}'s favourites can play: {self._skipped}")
        threading.Thread(target=self._run, args=(stop,), name="playlist", daemon=True).start()

    def skip(self) -> None:
        """Move the playlist on to its next favourite now. Raises LookupError."""
        with self._lock:
            if self._playlist is None:
                raise LookupError("no playlist is playing")
            self._advance()
            self._wake.notify_all()  # the thread waits for the new one's time

    def set_params(self, params: dict[str, Any]) -> None:
        """Change the running effect's parameters. Raises ParamError, LookupError."""
        with self._lock:
            self.engine.set_params(params)

    def stop(self) -> None:
        """Stop the playlist and the effect; the LEDs go off."""
        with self._lock:
            self._end_playlist()
            self._favourite = None
            self.engine.stop()

    def state(self) -> dict[str, Any]:
        with self._lock:
            st = self.engine.state()
            pl = self._playlist
            return {
                "effect": st["running"],
                "params": st["params"],
                "brightness": st["brightness"],
                "error": st["error"],
                "favourite": self._favourite if st["running"] else None,
                "playlist": None if pl is None else {
                    "id": pl["id"],
                    "name": pl["name"],
                    "item": self._order[self._pos],  # index in its items
                    "next_s": round(max(0.0, self._ends - time.monotonic()), 1),
                },
            }

    # -- the playlist -----------------------------------------------------------------

    def _end_playlist(self) -> None:
        self._stop.set()
        self._playlist = None
        self._wake.notify_all()

    def _next(self) -> bool:
        """Start the playlist's next favourite that can play (under the lock). Each pass
        picks up changes made to the playlist meanwhile."""
        pl = self._playlist
        for _ in range(len(pl["items"])):
            self._pos += 1
            if self._pos >= len(self._order):  # a new pass
                if self._order:
                    try:
                        self._playlist = pl = self.library.playlist(pl["id"])
                    except KeyError:
                        pass  # deleted while playing: carry on as it was
                    if not pl["items"]:
                        return False
                last = self._order[-1] if self._order else None
                n = len(pl["items"])
                self._order = list(range(n))
                if pl["shuffle"]:
                    random.shuffle(self._order)
                    if n > 1 and self._order[0] == last:  # not the same one twice running
                        self._order.append(self._order.pop(0))
                self._pos = 0
            item = pl["items"][self._order[self._pos]]
            try:
                fav = self.library.favourite(item["favourite"])
                self.engine.start(fav["effect"], fav["params"], crossfade_s=pl["crossfade_s"])
            except (KeyError, ParamError) as e:
                self._skipped = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
                log.warning("playlist %s: skipping %s: %s", pl["name"], item["favourite"],
                            self._skipped)
                continue
            self._favourite = fav["id"]
            self._ends = time.monotonic() + item["duration_s"]
            return True
        return False

    def _run(self, stop: threading.Event) -> None:
        with self._wake:
            while not stop.is_set():
                wait = self._ends - time.monotonic()
                if wait > 0:
                    self._wake.wait(wait)
                else:
                    self._advance()

    def _advance(self) -> None:
        """The next favourite, or the end of the playlist if none can play (under the lock)."""
        if not self._next():
            log.warning("playlist %s stopped: no favourite in it can play", self._playlist["name"])
            self._end_playlist()
            self.engine.stop()
