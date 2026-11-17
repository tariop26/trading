"""Shared helpers for the intraday signal tests (not a test file)."""
import _path  # noqa
from datetime import datetime, timezone

BAR_S = 900


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def make_bars(start_utc, ohlc):
    """Consecutive 15-minute bars (ts, o, h, l, c) from `start_utc`; ts = bar start."""
    t0 = int(start_utc.timestamp())
    return [(t0 + k * BAR_S, o, h, l, c) for k, (o, h, l, c) in enumerate(ohlc)]
