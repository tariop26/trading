"""Intraday signal foundations: closed 15-minute bars, ATR and Bollinger bands.

Pure functions, no I/O. A bar is a tuple (ts_utc_seconds, open, high, low, close) where
ts marks the START of the bar. A signal is a dict {"family", "side" ("haussier" |
"baissier"), "i", "stop_raw", "target_raw" (float | None), "detail"}; the entry is the
close of bar `i`.
"""
from datetime import datetime, timezone

import config
import sessions

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


ASIA_START_H, ASIA_END_H = 0, 7  # Asie range [00:00, 07:00) UTC


def session_ranges(bars, now_utc, params):
    """High/low of the opening ranges of the UTC day of `now_utc` (bars already closed).

    Asie covers [00:00, 07:00) UTC; Londres and New York cover [open, open + range_minutes)
    with the open computed in the session's own timezone (DST-aware). A range holds the
    bars whose start ts lies in [start, end); a range with no bar is omitted. Each entry is
    {"name", "day" (ISO date of the range start, UTC), "start", "end" (epoch s), "high", "low"}.
    """
    now = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
    midnight = int(now.astimezone(timezone.utc)
                   .replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    windows = [("Asie", midnight + ASIA_START_H * 3600, midnight + ASIA_END_H * 3600)]
    for name, label in (("London", "Londres"), ("New York", "New York")):
        start = int(sessions.open_utc(name, now).timestamp())
        windows.append((label, start, start + int(params["range_minutes"]) * 60))
    out = []
    for name, start, end in windows:
        inside = [b for b in bars if start <= b[0] < end]
        if not inside:
            continue
        out.append({"name": name,
                    "day": datetime.fromtimestamp(start, timezone.utc).date().isoformat(),
                    "start": start, "end": end,
                    "high": max(b[2] for b in inside), "low": min(b[3] for b in inside)})
    return out


def session_break(bars, i, ranges, params):
    """First close outside a session range, within break_window_hours after its end.

    Signal on bar `i` when ts_i >= end, the bar ends within the window, its close is
    strictly outside the range and no bar in [end, ts_i) already closed beyond that side.
    With several ranges triggering, the one with the latest end wins. None otherwise.
    """
    if not 0 <= i < len(bars):
        return None
    ts, close = bars[i][0], bars[i][4]
    window_s = params["break_window_hours"] * 3600
    best = None
    for r in ranges:
        end = r["end"]
        if ts < end or ts + BAR_S > end + window_s:
            continue
        if close > r["high"]:
            side, stop = "haussier", r["low"]
            already = any(b[4] > r["high"] for b in bars[:i] if end <= b[0] < ts)
        elif close < r["low"]:
            side, stop = "baissier", r["high"]
            already = any(b[4] < r["low"] for b in bars[:i] if end <= b[0] < ts)
        else:
            continue
        if already:
            continue
        if best is None or end > best[0]:
            best = (end, {"family": "session_break", "side": side, "i": i,
                          "stop_raw": stop, "target_raw": None, "detail": r["name"]})
    return best[1] if best else None
