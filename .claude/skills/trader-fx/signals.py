"""Setups, ATR, trend, levels and the Asia range from Yahoo bars. Standard library only.

Everything here is pure: bars and a clock go in, numbers come out. A daily bar is
only ever used once it is complete (complete_daily), because Yahoo returns the
in-progress daily bar for forex and it must never count as a close.
"""
from datetime import datetime, timedelta, timezone

MIN_DAILY = 30
ASIA_START_H = 0
ASIA_END_H = 7


# ---------------------------------------------------------------- setups
# Same definitions as trader-scanner/scan.py (rsi, find_setups). Reimplemented here
# so production code never imports the scanner; a test checks the two agree.

def rsi(closes, n=14):
    """Wilder's RSI on closes."""
    if len(closes) < n + 1:
        return None
    g = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    lo = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag, al = sum(g[:n]) / n, sum(lo[:n]) / n
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + lo[i]) / n
    return 100 - 100 / (1 + ag / al) if al else 100.0


def find_setups(closes):
    """closes (oldest first, >= 30) -> (setup keys, numbers)."""
    c = closes
    last = c[-1]
    hi20 = max(c[-21:-1])
    ma20 = sum(c[-20:]) / 20.0
    ma20_prev = sum(c[-21:-1]) / 20.0
    run = c[-6] / c[-16] - 1
    rng5 = (max(c[-5:]) - min(c[-5:])) / last
    r = rsi(c)
    r_prev = rsi(c[:-1])
    tags = []
    if last > hi20:
        tags.append("breakout_20d")
    if run > 0.10 and rng5 < 0.05:
        tags.append("bull_flag")
    if c[-2] < ma20_prev and last > ma20:
        tags.append("reclaim_ma20")
    if r is not None and r < 30:
        tags.append("oversold")
    if r_prev is not None and r_prev < 30 and last > c[-2]:
        tags.append("oversold_bounce")
    return tags, {"rsi": r, "rsi_prev": r_prev, "high20": hi20, "ma20": ma20,
                  "run_pct": run * 100, "range5_pct": rng5 * 100}


# ---------------------------------------------------------------- daily bars

def _local_date(now_utc, gmtoffset):
    """Calendar date of now_utc in the series' own timezone."""
    return (now_utc.astimezone(timezone.utc) + timedelta(seconds=gmtoffset)).date()


def complete_daily(series, now_utc):
    """-> [(local date, o, h, l, c)], one bar per date, oldest first.

    The local date of a bar is (ts + gmtoffset). A bar dated today (or later) in the
    series' own timezone is still in progress and is dropped; on a weekend the last
    bar is Friday's, which is complete, so it stays."""
    off = timedelta(seconds=series.gmtoffset)
    today = _local_date(now_utc, series.gmtoffset)
    out = {}
    for ts, o, h, l, c in series.bars:
        d = (datetime.fromtimestamp(ts, timezone.utc) + off).date()
        if d >= today:
            continue
        out[d] = (d, o, h, l, c)  # a later duplicate for the same date wins
    return [out[d] for d in sorted(out)]


def atr(daily, n=14):
    """Wilder's ATR over daily (date, o, h, l, c) bars; None under n + 1 bars."""
    if len(daily) < n + 1:
        return None
    tr = []
    for i in range(1, len(daily)):
        _, _, h, l, _ = daily[i]
        pc = daily[i - 1][4]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(tr[:n]) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    return a


def trend(closes):
    """'up' if the close is above the 50-day average and the 20-day average is above
    the 50-day; 'down' for the reverse; 'mixed' otherwise. None under 50 closes."""
    if len(closes) < 50:
        return None
    last = closes[-1]
    ma20 = sum(closes[-20:]) / 20.0
    ma50 = sum(closes[-50:]) / 50.0
    if last > ma50 and ma20 > ma50:
        return "up"
    if last < ma50 and ma20 < ma50:
        return "down"
    return "mixed"


def levels(daily, today=None):
    """Previous day's high/low, previous ISO week's high/low and the 20-session
    high/low. Missing data gives None.

    The previous week is relative to `today` (default: the last bar's date). On a
    Saturday or Sunday, today moves to the next Monday, so the previous week is the
    one that just ended (Friday's week)."""
    if not daily:
        return {"prev_high": None, "prev_low": None, "week_high": None,
                "week_low": None, "high20": None, "low20": None}
    last_d, _, ph, pl, _ = daily[-1]
    ref = today or last_d
    if ref.weekday() >= 5:
        ref += timedelta(days=7 - ref.weekday())
    wk = (ref - timedelta(days=7)).isocalendar()[:2]
    week = [b for b in daily if b[0].isocalendar()[:2] == wk]
    last20 = daily[-20:]
    return {
        "prev_high": ph,
        "prev_low": pl,
        "week_high": max(b[2] for b in week) if week else None,
        "week_low": min(b[3] for b in week) if week else None,
        "high20": max(b[2] for b in last20),
        "low20": min(b[3] for b in last20),
    }


# ---------------------------------------------------------------- intraday

def asia_range(hourly, now_utc):
    """Asia session of the UTC day of now_utc: 1h bars from 00:00 up to (not
    including) 07:00 UTC, plus the day's high/low since 00:00 UTC. Bars after now
    are ignored. None when there is no Asia bar yet today."""
    now = now_utc.astimezone(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    t0 = int(start.timestamp())
    t_asia_end = int((start + timedelta(hours=ASIA_END_H)).timestamp())
    t_now = int(now.timestamp())
    day = [b for b in hourly.bars if t0 <= b[0] <= t_now]
    asia = [b for b in day if b[0] < t_asia_end]
    if not asia:
        return None
    return {
        "asia_high": max(b[2] for b in asia),
        "asia_low": min(b[3] for b in asia),
        "day_high": max(b[2] for b in day),
        "day_low": min(b[3] for b in day),
    }


# ---------------------------------------------------------------- one symbol

def analyze(symbol, name, daily, now_utc):
    """None under MIN_DAILY complete sessions, else the symbol's swing summary."""
    bars = complete_daily(daily, now_utc)
    if len(bars) < MIN_DAILY:
        return None
    closes = [b[4] for b in bars]
    last = closes[-1]
    a = atr(bars)
    tags, _ = find_setups(closes)
    return {
        "symbol": symbol,
        "name": name,
        "last": last,
        "rsi": rsi(closes),
        "atr_pct": (a / last * 100.0) if (a is not None and last) else None,
        "trend": trend(closes),
        "setups": tags,
        "levels": levels(bars, _local_date(now_utc, daily.gmtoffset)),
        "last_bar_date": bars[-1][0].isoformat(),
    }
