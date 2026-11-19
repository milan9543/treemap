"""The colour code every LED flashes during a scan, so the camera can tell them apart.

All LEDs flash at once. Time is split into symbols of ``symbol_s`` seconds; a cycle is
one **sync** symbol (every LED white) followed by ``CODE_LEN`` colour symbols (red,
green or blue) that spell the LED's codeword. An LED is never dark, so the camera can
follow its blob from frame to frame while it spells out its number.

Codewords are ``DATA_LEN`` base-3 digits plus one check digit (their sum mod 3): a
single misread symbol is caught, and a single *missing* symbol (an LED hidden for a
moment) can be filled in. 3^6 = 729 codewords cover up to 728 LEDs (the all-red one is
left out, because it looks like a stuck colour).
"""

from __future__ import annotations

import numpy as np

DATA_LEN = 6
CODE_LEN = DATA_LEN + 1  # + check digit
CYCLE = CODE_LEN + 1  # + sync
SYNC = 3  # symbol value of the white sync
MAX_LEDS = 3**DATA_LEN - 1
# Unit colour of each symbol: red, green, blue, white (sync).
SYMBOL_RGB = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=float)


def codewords(n: int) -> np.ndarray:
    """``(n, CODE_LEN)`` int codewords, LED ``i`` gets row ``i``."""
    if not 1 <= n <= MAX_LEDS:
        raise ValueError(f"the scan code covers 1-{MAX_LEDS} LEDs, not {n}")
    k = np.arange(1, n + 1)  # skip 0: the all-red codeword
    digits = (k[:, None] // 3 ** np.arange(DATA_LEN)[::-1]) % 3
    return np.concatenate([digits, digits.sum(axis=1, keepdims=True) % 3], axis=1)


def code_lookup(n: int) -> dict[tuple[int, ...], int]:
    """Codeword -> LED index."""
    return {tuple(int(d) for d in c): i for i, c in enumerate(codewords(n))}


def check_ok(code: np.ndarray | list[int]) -> bool:
    c = np.asarray(code)
    return int(c[:DATA_LEN].sum()) % 3 == int(c[DATA_LEN])


def repair(symbols: list[int | None]) -> list[int] | None:
    """Fill at most one missing symbol from the check digit; None if it can't be (two or
    more missing) or the result fails the check."""
    missing = [k for k, s in enumerate(symbols) if s is None]
    if len(missing) > 1:
        return None
    out = [0 if s is None else int(s) for s in symbols]
    if missing:
        k = missing[0]
        if k < DATA_LEN:
            out[k] = (out[DATA_LEN] - (sum(out[:DATA_LEN]) - out[k])) % 3
        else:
            out[k] = sum(out[:DATA_LEN]) % 3
    return out if check_ok(out) else None


def symbol_index(t: float, symbol_s: float) -> int:
    """Which symbol of the cycle is showing at time ``t`` (0 = sync)."""
    return int(np.floor(t / symbol_s)) % CYCLE


def frame_at(slot: int, codes: np.ndarray, brightness: int) -> np.ndarray:
    """``(n, 3)`` uint8 LED colours for cycle slot ``slot`` (0 = sync)."""
    sym = np.full(len(codes), SYNC) if slot == 0 else codes[:, slot - 1]
    return np.round(SYMBOL_RGB[sym] * brightness).astype(np.uint8)
