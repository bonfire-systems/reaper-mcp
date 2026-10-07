"""Conversions between the units tools speak and the units REAPER stores."""

import math

# REAPER's faders bottom out at -150 dB, which it stores as linear 0.
SILENCE_DB = -150.0


def db_to_linear(db: float) -> float:
    if db <= SILENCE_DB:
        return 0.0
    return 10 ** (db / 20.0)


def linear_to_db(linear: float) -> float:
    """The inverse of db_to_linear; silence reads as SILENCE_DB, never -inf,
    so a reply stays valid JSON."""
    if linear <= 0:
        return SILENCE_DB
    return max(SILENCE_DB, 20.0 * math.log10(linear))
