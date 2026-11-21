"""The colour code every LED flashes during a scan, so the camera can tell them apart.

All LEDs flash at once. Time is split into symbols of ``symbol_s`` seconds; a cycle is
one **sync** symbol (every LED white) followed by the colour symbols (red, green or
blue) that spell the LED's codeword. An LED is never dark, so the camera can follow its
blob from frame to frame while it spells out its number.

Codewords are base-3 digits plus one check digit (their sum mod 3): a single misread
symbol is caught, and a single *missing* symbol (an LED hidden for a moment) can be
filled in. There are as many digits as the LED count needs, and at least 6: 6 digits
cover up to 728 LEDs, 7 up to 2186, 8 up to 6560 (the all-red codeword is left out,
because it looks like a stuck colour). Each extra digit makes a cycle one symbol longer.
"""

from __future__ import annotations

import numpy as np

MIN_DATA_LEN = 6  # digits for up to 728 LEDs; more LEDs get longer codes
MAX_DATA_LEN = 8
SYNC = 3  # symbol value of the white sync
MAX_LEDS = 3**MAX_DATA_LEN - 1
# Unit colour of each symbol: red, green, blue, white (sync).
SYMBOL_RGB = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=float)


def data_len(n: int) -> int:
    """Base-3 digits the codewords of ``n`` LEDs need (at least MIN_DATA_LEN)."""
    if not 1 <= n <= MAX_LEDS:
        raise ValueError(f"the scan code covers 1-{MAX_LEDS} LEDs, not {n}")
    d = MIN_DATA_LEN
    while 3**d - 1 < n:
        d += 1
    return d


def codewords(n: int) -> np.ndarray:
    """``(n, data_len(n) + 1)`` int codewords (digits, then the check digit); LED ``i``
    gets row ``i``. The code length is ``codewords(n).shape[1]``."""
    d = data_len(n)
    k = np.arange(1, n + 1)  # skip 0: the all-red codeword
    digits = (k[:, None] // 3 ** np.arange(d)[::-1]) % 3
    return np.concatenate([digits, digits.sum(axis=1, keepdims=True) % 3], axis=1)


def code_lookup(n: int) -> dict[tuple[int, ...], int]:
    """Codeword -> LED index."""
    return {tuple(int(d) for d in c): i for i, c in enumerate(codewords(n))}


def check_ok(code: np.ndarray | list[int]) -> bool:
    c = np.asarray(code)
    return int(c[:-1].sum()) % 3 == int(c[-1])


def repair(symbols: list[int | None]) -> list[int] | None:
    """Fill at most one missing symbol from the check digit; None if it can't be (two or
    more missing) or the result fails the check."""
    missing = [k for k, s in enumerate(symbols) if s is None]
    if len(missing) > 1:
        return None
    out = [0 if s is None else int(s) for s in symbols]
    d = len(out) - 1  # data digits; the last is the check digit
    if missing:
        k = missing[0]
        if k < d:
            out[k] = (out[d] - (sum(out[:d]) - out[k])) % 3
        else:
            out[k] = sum(out[:d]) % 3
    return out if check_ok(out) else None


def symbol_index(t: float, symbol_s: float, code_len: int) -> int:
    """Which symbol of the cycle (sync + ``code_len`` symbols) is showing at time ``t``
    (0 = sync)."""
    return int(np.floor(t / symbol_s)) % (code_len + 1)


def frame_at(slot: int, codes: np.ndarray, brightness: int) -> np.ndarray:
    """``(n, 3)`` uint8 LED colours for cycle slot ``slot`` (0 = sync)."""
    sym = np.full(len(codes), SYNC) if slot == 0 else codes[:, slot - 1]
    return np.round(SYMBOL_RGB[sym] * brightness).astype(np.uint8)
