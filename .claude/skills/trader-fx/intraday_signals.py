"""Intraday signal foundations: closed 15-minute bars, ATR and Bollinger bands.

Pure functions, no I/O. A bar is a tuple (ts_utc_seconds, open, high, low, close) where
ts marks the START of the bar. A signal is a dict {"family", "side" ("haussier" |
"baissier"), "i", "stop_raw", "target_raw" (float | None), "detail"}; the entry is the
close of bar `i`.
"""
import config

BAR_S = 900
FAMILIES = config.INTRADAY_FAMILIES


def closed_bars(bars, now_utc):
    """Bars whose 15 minutes are over at `now_utc` (ts + BAR_S <= now), sorted by ts.

    A duplicated ts keeps its last occurrence; malformed entries are skipped.
    """
    now = now_utc.timestamp()
    by_ts = {}
    for b in bars:
        try:
            if len(b) != 5:
                continue
            ts, o, h, l, c = b
            ts, o, h, l, c = float(ts), float(o), float(h), float(l), float(c)
        except (TypeError, ValueError):
            continue
        if ts + BAR_S <= now:
            by_ts[ts] = b
    return [by_ts[ts] for ts in sorted(by_ts)]


def atr_bars(bars, i, n=14):
    """Wilder ATR of the true ranges of bars[0..i]; None under n + 1 bars."""
    if i + 1 < n + 1:
        return None
    tr = []
    for k in range(1, i + 1):
        _, _, h, l, _ = bars[k]
        pc = bars[k - 1][4]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(tr[:n]) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    return a


def bollinger(bars, i, period, std):
    """(mid, upper, lower) of the `period` closes ending at index i (population sd);
    None for a short series or a zero deviation."""
    if period < 1 or i + 1 < period:
        return None
    closes = [bars[k][4] for k in range(i - period + 1, i + 1)]
    if max(closes) == min(closes):  # exact flat window: avoid a float-rounding sd of ~1e-17
        return None
    mid = sum(closes) / period
    sd = (sum((c - mid) ** 2 for c in closes) / period) ** 0.5
    if sd == 0:
        return None
    return (mid, mid + std * sd, mid - std * sd)


def signal_params(config):
    """config["intraday"] plus the plan's stop_atr_mult and target_r (no validation)."""
    return dict(config["intraday"],
                stop_atr_mult=config["plan"]["stop_atr_mult"],
                target_r=config["plan"]["target_r"])
