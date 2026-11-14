"""Generates tests/fixtures/briefing_sample.json through the REAL briefing.build_briefing.

Synthetic series only, no network. Run from the repository root to rewrite the fixture:

    python3 .claude/skills/trader-fx/tests/make_sample_fixture.py

test_page.py checks that the committed fixture equals build_sample(), so the fixture cannot
drift from the real key set of briefing.json again.
"""
import _path  # noqa
import json
import math
import os
from datetime import date, datetime, timezone

import briefing
import config
import data
import test_briefing as tb

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "briefing_sample.json")

UNIVERSE = [("EURUSD=X", "EUR/USD"), ("GBPUSD=X", "GBP/USD"), ("AUDUSD=X", "AUD/USD"),
            ("USDCAD=X", "USD/CAD"), ("NZDUSD=X", "NZD/USD"), ("USDJPY=X", "USD/JPY"),
            ("USDCHF=X", "USD/CHF"), ("USDSEK=X", "USD/SEK"), ("GC=F", "Or"),
            ("CL=F", "Pétrole WTI"), ("^FCHI", "CAC 40"), ("^GDAXI", "DAX")]

# the Yahoo calendar rows of the week, as economic_calendar produces them
EVENTS = [
    {"utc": "2026-11-10T13:30:00+00:00", "time_paris": "14:30", "time_ny": "08:30",
     "date_paris": "2026-11-10", "date_ny": "2026-11-10", "currency": "USD",
     "title": "CPI m/m", "impact": "High", "forecast": "0.3%", "previous": "0.4%"},
    {"utc": "2026-11-10T19:00:00+00:00", "time_paris": "20:00", "time_ny": "14:00",
     "date_paris": "2026-11-10", "date_ny": "2026-11-10", "currency": "USD",
     "title": "FOMC Member Speaks", "impact": "High", "forecast": "", "previous": ""},
    {"utc": "2026-11-12T09:30:00+00:00", "time_paris": "10:30", "time_ny": "04:30",
     "date_paris": "2026-11-12", "date_ny": "2026-11-12", "currency": "GBP",
     "title": "GDP m/m", "impact": "High", "forecast": "0.1%", "previous": "-0.1%"},
]


def rising(base, n=55, step=0.0015, wobble=0.003):
    """A rising series with a little noise, closing on a new 20-session high."""
    closes = [base * (1 + step * i + wobble * math.sin(i * 1.7)) for i in range(n)]
    closes[-1] = max(closes[-21:-1]) * 1.012
    return closes


def calm(base, n=55):
    """No rule of either side fires on it (same oscillation as test_briefing.neutral)."""
    return [base * (1 + 0.01 * math.sin(i / 3.0)) for i in range(n)]


def overbought_pullback(base, n=55):
    """Overbought yesterday, a small drop today: 'overbought_reject', no long rule."""
    return [base * c for c in tb.short_only(n)]


def hourly_eurusd():
    """1 h bars of the day after the close, inside the EURUSD plan (nothing crossed)."""
    t0 = int(datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp())
    base = 1.1890
    return data.Series(bars=[(t0 + h * 3600, base, base * (1.0007 + h * 0.0001),
                              base * 0.9994, base * (1 + 0.0002 * math.sin(h)))
                             for h in range(10)], gmtoffset=0)


def hourly_fchi():
    """1 h bars of the day after the close that fall through the ^FCHI stop."""
    t0 = int(datetime(2026, 11, 10, 8, tzinfo=timezone.utc).timestamp())
    closes = [8180.0, 8160.0, 8140.0, 8120.0, 8110.0]
    return data.Series(bars=[(t0 + h * 3600, c + 10, c + 15, c - 5, c)
                             for h, c in enumerate(closes)], gmtoffset=0)


def build_sample():
    """The sample briefing: 3 ideas (ok forex bullish, to_confirm bullish, too_wide bearish),
    2 skipped ideas (one correlated, one beyond the display limit with the same score as
    the last shown: ties_at_cutoff 1), the cumulated risk over a 0.75 % cap, 1 h bars
    after the close on two ideas (the ^FCHI stop already crossed), the default account
    (source "default"), 1 short-only hit, a partial calendar, one failed symbol."""
    bases = {"EURUSD=X": 1.0852, "GBPUSD=X": 1.2644, "AUDUSD=X": 0.6531,
             "USDCAD=X": 1.3912, "NZDUSD=X": 0.5918, "USDJPY=X": 151.84,
             "USDCHF=X": 0.8827, "GC=F": 4012.5, "CL=F": 71.4, "^FCHI": 7480.0,
             "^GDAXI": 19500.0}
    shape = {"EURUSD=X": rising, "GBPUSD=X": rising, "^FCHI": rising, "^GDAXI": rising,
             "CL=F": overbought_pullback}
    daily = {sym: tb.series((shape.get(sym, calm))(base), end=date(2026, 11, 9))
             for sym, base in bases.items()}
    failed = [{"symbol": "USDSEK=X", "reason": "no data"}]
    cal = {"status": "partial", "events": EVENTS,
           "reason": "next week: pas encore publié (HTTP 404)"}
    cfg = config.defaults()
    cfg["ideas"]["max_per_exposure"] = 1          # GBPUSD shares the short USD leg of EURUSD
    cfg["ideas"]["max_shown"] = 3                 # ^GDAXI ties with the last shown idea
    cfg["risk"]["max_total_pct"] = 0.75           # 497 + 500 counted > 750: over the cap
    cfg["contracts"] = {"CL=F": {"usd_per_point": 1000, "step": 1, "min": 1}}   # 1 lot minimum
    extra = ["Barres 1 h indisponibles pour 2 symbole(s) en alerte (CL=F, ^GDAXI) : "
             "plage asiatique non calculée."]
    hourly = {"EURUSD=X": hourly_eurusd(), "^FCHI": hourly_fchi()}
    return briefing.build_briefing(UNIVERSE, daily, failed, hourly,
                                   cal, tb.TUE, extra_warnings=extra, config=cfg)


def main():
    with open(FIXTURE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(build_sample(), f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("written:", FIXTURE)


if __name__ == "__main__":
    main()
