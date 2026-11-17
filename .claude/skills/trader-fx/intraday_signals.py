"""Intraday signal foundations: closed 15-minute bars, ATR and Bollinger bands.

Pure functions, no I/O. A bar is a tuple (ts_utc_seconds, open, high, low, close) where
ts marks the START of the bar. A signal is a dict {"family", "side" ("haussier" |
"baissier"), "i", "stop_raw", "target_raw" (float | None), "detail"}; the entry is the
close of bar `i`.
"""
from datetime import datetime, timezone

import config
import sessions
import signals

BAR_S = 900
FAMILIES = config.INTRADAY_FAMILIES


def _signal(family, side, i, stop_raw, target_raw, detail=""):
    """The standard signal dict shared by every family."""
    return {"family": family, "side": side, "i": i,
            "stop_raw": stop_raw, "target_raw": target_raw, "detail": detail}


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
            best = (end, _signal("session_break", side, i, stop, None, r["name"]))
    return best[1] if best else None


def bb_return(bars, i, params):
    """Return inside the Bollinger bands after a close outside them.

    baissier when the close of bar i - 1 is above the upper band of i - 1 and the close of
    bar i is back at or under the upper band of i; haussier in mirror under the lower band.
    Stop = high (baissier) or low (haussier) of bar i - 1; target = middle band at i.
    None for a short or flat series (bands undefined).
    """
    if not 1 <= i < len(bars):
        return None
    period, std = params["bb_period"], params["bb_std"]
    prev_bands = bollinger(bars, i - 1, period, std)
    bands = bollinger(bars, i, period, std)
    if prev_bands is None or bands is None:
        return None
    prev_close, close = bars[i - 1][4], bars[i][4]
    mid = bands[0]
    if prev_close > prev_bands[1] and close <= bands[1]:
        return _signal("bb_return", "baissier", i, bars[i - 1][2], mid)
    if prev_close < prev_bands[2] and close >= bands[2]:
        return _signal("bb_return", "haussier", i, bars[i - 1][3], mid)
    return None


def rsi_exit(bars, i, params):
    """RSI leaving an extreme zone: haussier when it crosses back up through rsi_low,
    baissier when it crosses back down through rsi_high.

    Stop = close -/+ stop_atr_mult x ATR; no target. None when the RSI is undefined (short
    series) or the ATR is missing or zero.
    """
    if not 1 <= i < len(bars):
        return None
    closes = [b[4] for b in bars[:i + 1]]
    period = params["rsi_period"]
    now = signals.rsi(closes, period)
    prev = signals.rsi(closes[:-1], period)
    if now is None or prev is None:
        return None
    if prev < params["rsi_low"] and now >= params["rsi_low"]:
        side, sign = "haussier", -1
    elif prev > params["rsi_high"] and now <= params["rsi_high"]:
        side, sign = "baissier", 1
    else:
        return None
    atr = atr_bars(bars, i)
    if atr is None or atr <= 0:
        return None
    return _signal("rsi_exit", side, i, closes[-1] + sign * params["stop_atr_mult"] * atr, None)


def engulfing(bars, i, params):
    """Engulfing candle after a run of opposite candles.

    haussier: bar i closes above its open, the `engulfing_min_prior` bars i-k..i-1 all close
    strictly below their open (a doji breaks the run) and the body of bar i contains the
    body of bar i - 1 (edges may be equal). Stop = low of bar i; no target. baissier is the
    mirror (stop = high of bar i). None when fewer than k bars precede i.
    """
    k = max(1, int(params["engulfing_min_prior"]))
    if not k <= i < len(bars):
        return None
    _, o, h, l, c = bars[i]
    prev_o, prev_c = bars[i - 1][1], bars[i - 1][4]
    contains = min(o, c) <= min(prev_o, prev_c) and max(o, c) >= max(prev_o, prev_c)
    if not contains:
        return None
    run = bars[i - k:i]
    if c > o and all(b[4] < b[1] for b in run):
        return _signal("engulfing", "haussier", i, l, None)
    if c < o and all(b[4] > b[1] for b in run):
        return _signal("engulfing", "baissier", i, h, None)
    return None


FRACTAL_LOOKBACK = 50


def _fractals(bars, i):
    """Williams fractals confirmed at bar i: (indices of highs, indices of lows), oldest first.

    A fractal at k beats the two bars on each side (strictly); it is confirmed once its
    right-hand bars are closed relative to i (k + 2 <= i - 1) and searched back to
    i - FRACTAL_LOOKBACK. Only bars up to i - 1 are read.
    """
    highs, lows = [], []
    for k in range(max(2, i - FRACTAL_LOOKBACK), i - 2):
        near = (k - 2, k - 1, k + 1, k + 2)
        if all(bars[k][2] > bars[j][2] for j in near):
            highs.append(k)
        if all(bars[k][3] < bars[j][3] for j in near):
            lows.append(k)
    return highs, lows


def _fractal_side(bars, i, params, side):
    """One direction of fractal_break (see there); None when it does not trigger."""
    highs, lows = _fractals(bars, i)
    bull = side == "haussier"
    own, opposite = (highs, lows) if bull else (lows, highs)
    if not own:
        return None
    k = own[-1]  # the latest confirmed fractal only: no fallback on an older one
    close = bars[i][4]
    if bull:
        level = bars[k][2]
        if not close > level or any(bars[j][4] > level for j in range(k + 3, i)):
            return None
    else:
        level = bars[k][3]
        if not close < level or any(bars[j][4] < level for j in range(k + 3, i)):
            return None
    stop = None
    if opposite:
        m = opposite[-1]
        if bull and bars[m][3] < close:
            stop = bars[m][3]
        elif not bull and bars[m][2] > close:
            stop = bars[m][2]
    if stop is None:
        atr = atr_bars(bars, i)
        if atr is None or atr <= 0:
            return None
        stop = close - params["stop_atr_mult"] * atr if bull else close + params["stop_atr_mult"] * atr
    return _signal("fractal_break", side, i, stop, None)


def fractal_break(bars, i, params):
    """Close beyond the latest confirmed Williams fractal that no close had broken yet.

    haussier: close of bar i above the high of the latest confirmed fractal high and no close
    from k + 3 to i - 1 above it. Stop = low of the latest confirmed fractal low when it is
    under the close, else close - stop_atr_mult x ATR (None without a usable ATR). baissier is
    the mirror. Both directions on the same bar give None. No target.
    """
    if not 0 <= i < len(bars):
        return None
    up = _fractal_side(bars, i, params, "haussier")
    down = _fractal_side(bars, i, params, "baissier")
    if up is not None and down is not None:
        return None
    return up or down


def detect_all(bars, i, ranges, params):
    """Signals of bar i for every family of params["families"], in FAMILIES order."""
    out = []
    for family in FAMILIES:
        if family not in params["families"]:
            continue
        if family == "session_break":
            sig = session_break(bars, i, ranges, params)
        elif family == "bb_return":
            sig = bb_return(bars, i, params)
        elif family == "fractal_break":
            sig = fractal_break(bars, i, params)
        elif family == "engulfing":
            sig = engulfing(bars, i, params)
        else:
            sig = rsi_exit(bars, i, params)
        if sig is not None:
            out.append(sig)
    return out
