import _path  # noqa
import importlib.util
import os
import unittest
from datetime import date, datetime, timezone

import data
import signals

HERE = os.path.dirname(os.path.abspath(__file__))
SCAN_PY = os.path.join(HERE, "..", "..", "trader-scanner", "scan.py")
FIX = os.path.join(HERE, "fixtures")

DAY = 86400


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def ts(y, m, d, h=0, mi=0):
    return int(utc(y, m, d, h, mi).timestamp())


def load_scan():
    spec = importlib.util.spec_from_file_location("scan_under_test", SCAN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def flat_bars(n, start=date(2026, 9, 1), price=1.0, rng=1.0):
    """n consecutive calendar-day bars at 00:00 UTC, high-low == rng, constant close."""
    t0 = ts(start.year, start.month, start.day)
    return [(t0 + i * DAY, price, price + rng / 2, price - rng / 2, price) for i in range(n)]


class TestRsi(unittest.TestCase):
    def test_rsi_all_gains_is_100_and_short_series_is_none(self):
        self.assertEqual(signals.rsi([float(i) for i in range(1, 30)]), 100.0)
        self.assertIsNone(signals.rsi([1.0] * 14))
        self.assertIsNotNone(signals.rsi([1.0, 2.0] * 8))


class TestFindSetups(unittest.TestCase):
    def series(self):
        flat = [100.0 + (i % 3) * 0.2 for i in range(40)]
        breakout = flat[:-1] + [max(flat) + 5.0]
        # a clean flag: strong run, then 5 tight closes
        flag = [100.0 + i * 2.0 for i in range(25)] + [150.0, 150.5, 150.2, 150.6, 150.3]
        reclaim = [100.0] * 22 + [99.0 - i * 0.1 for i in range(7)] + [104.0]
        sold = [100.0 - i * 1.2 for i in range(30)]
        bounce = sold + [sold[-1] + 2.0]
        return [breakout, flag, reclaim, sold, bounce]

    def test_find_setups_matches_scan_py(self):
        scan = load_scan()
        seen = set()
        for closes in self.series():
            mine = signals.find_setups(closes)
            theirs = scan.find_setups(closes)
            self.assertEqual(mine[0], theirs[0])
            self.assertEqual(mine[1], theirs[1])
            seen.update(mine[0])
        self.assertEqual(
            seen, {"breakout_20d", "bull_flag", "reclaim_ma20", "oversold", "oversold_bounce"})
        self.assertEqual(signals.rsi(self.series()[3]), scan.rsi(self.series()[3]))


class TestCompleteDaily(unittest.TestCase):
    def bars(self):
        return [(ts(2026, 11, 11), 1.0, 1.2, 0.9, 1.1),
                (ts(2026, 11, 12), 1.1, 1.3, 1.0, 1.2),
                (ts(2026, 11, 13), 1.2, 1.25, 1.15, 1.22)]

    def test_complete_daily_drops_todays_partial_bar(self):
        s = data.Series(bars=self.bars(), gmtoffset=0)
        out = signals.complete_daily(s, utc(2026, 11, 13, 14, 0))
        self.assertEqual([d for d, *_ in out], [date(2026, 11, 11), date(2026, 11, 12)])
        self.assertEqual(out[-1], (date(2026, 11, 12), 1.1, 1.3, 1.0, 1.2))

    def test_complete_daily_keeps_last_bar_on_saturday(self):
        s = data.Series(bars=self.bars(), gmtoffset=0)
        out = signals.complete_daily(s, utc(2026, 11, 14, 10, 0))
        self.assertEqual(out[-1][0], date(2026, 11, 13))
        self.assertEqual(len(out), 3)

    def test_complete_daily_uses_local_date_from_gmtoffset(self):
        # Sydney-style +11h: a bar stamped 13:00 UTC on the 12th is local 00:00 on the 13th.
        s = data.Series(bars=[(ts(2026, 11, 11, 13), 1, 2, 0.5, 1.5),
                              (ts(2026, 11, 12, 13), 1, 2, 0.5, 1.6)], gmtoffset=39600)
        out = signals.complete_daily(s, utc(2026, 11, 12, 20, 0))  # local 13th 07:00
        self.assertEqual([d for d, *_ in out], [date(2026, 11, 12)])

    def test_complete_daily_one_bar_per_date_later_wins(self):
        s = data.Series(bars=[(ts(2026, 11, 10, 0), 1, 2, 0.5, 1.5),
                              (ts(2026, 11, 10, 5), 1, 2, 0.5, 1.7)], gmtoffset=0)
        out = signals.complete_daily(s, utc(2026, 11, 13, 9))
        self.assertEqual(out, [(date(2026, 11, 10), 1, 2, 0.5, 1.7)])

    def test_complete_daily_on_real_fixture(self):
        with open(os.path.join(FIX, "eurusd_1d.json"), encoding="utf-8") as f:
            s = data.parse_chart(f.read(), "EURUSD=X")
        last_ts = s.bars[-1][0]
        now = datetime.fromtimestamp(last_ts, timezone.utc)
        out = signals.complete_daily(s, now)
        dates = [d for d, *_ in out]
        self.assertEqual(dates, sorted(set(dates)))
        self.assertLess(dates[-1], now.date())


class TestAtr(unittest.TestCase):
    def test_atr_constant_range_series(self):
        d = [(date(2026, 9, 1), p, p + 0.5, p - 0.5, p) for p in [1.0] * 20]
        self.assertAlmostEqual(signals.atr(d), 1.0)

    def test_atr_short_series_is_none(self):
        d = [(date(2026, 9, 1), 1, 1.5, 0.5, 1)] * 14
        self.assertIsNone(signals.atr(d))

    def test_atr_counts_gaps(self):
        # every bar has high-low 0.2 but closes gap 1.0 from the previous close
        d = [(date(2026, 9, 1), 0, 0, 0, 0)]
        c = 0.0
        for _ in range(20):
            c += 1.0
            d.append((date(2026, 9, 1), c, c + 0.1, c - 0.1, c))
        self.assertAlmostEqual(signals.atr(d), 1.1)


class TestTrend(unittest.TestCase):
    def test_trend_up_down_mixed(self):
        up = [100.0 + i for i in range(60)]
        down = [200.0 - i for i in range(60)]
        mixed = [100.0 + i for i in range(50)] + [150.0 - 4 * i for i in range(10)]
        self.assertEqual(signals.trend(up), "up")
        self.assertEqual(signals.trend(down), "down")
        self.assertEqual(signals.trend(mixed), "mixed")

    def test_trend_needs_50_closes(self):
        self.assertIsNone(signals.trend([1.0] * 49))


class TestLevels(unittest.TestCase):
    def test_levels_use_previous_iso_week(self):
        # 2026-11-09 is a Monday. Previous week: 11-02..11-06. Current: 11-09..11-12.
        def bar(d, h, l):
            return (d, 1.0, h, l, 1.0)
        daily = [bar(date(2026, 11, 2), 1.50, 1.10), bar(date(2026, 11, 3), 1.60, 1.20),
                 bar(date(2026, 11, 6), 1.40, 1.05),
                 bar(date(2026, 11, 9), 9.00, 0.01), bar(date(2026, 11, 10), 1.30, 1.15),
                 bar(date(2026, 11, 12), 1.35, 1.12)]
        lv = signals.levels(daily)
        self.assertEqual(lv["week_high"], 1.60)
        self.assertEqual(lv["week_low"], 1.05)
        self.assertEqual(lv["prev_high"], 1.35)
        self.assertEqual(lv["prev_low"], 1.12)
        self.assertEqual(lv["high20"], 9.00)
        self.assertEqual(lv["low20"], 0.01)
        self.assertEqual(set(lv), {"prev_high", "prev_low", "week_high", "week_low",
                                   "high20", "low20"})

    def test_levels_high20_uses_last_20_bars_only(self):
        daily = [(date(2026, 9, 1), 1, 50.0, 0.001, 1)] + \
                [(date(2026, 10, 1), 1, 2.0, 1.0, 1)] * 20
        lv = signals.levels(daily)
        self.assertEqual(lv["high20"], 2.0)
        self.assertEqual(lv["low20"], 1.0)

    def friday_bars(self):
        # Previous week 11-02..11-06 (Mon..Fri); Friday 11-06 is the last complete bar
        # of a week that just ended when the briefing runs on Mon 11-09 or the weekend.
        # The week before (10-26..10-30) must never be the answer.
        def bar(d, h, l):
            return (d, 1.0, h, l, 1.0)
        return [bar(date(2026, 10, 27), 8.00, 0.50), bar(date(2026, 10, 30), 7.00, 0.60),
                bar(date(2026, 11, 2), 1.50, 1.10), bar(date(2026, 11, 3), 1.60, 1.20),
                bar(date(2026, 11, 6), 1.40, 1.05)]

    def test_levels_monday_uses_the_week_that_just_ended(self):
        lv = signals.levels(self.friday_bars(), today=date(2026, 11, 9))
        self.assertEqual((lv["week_high"], lv["week_low"]), (1.60, 1.05))

    def test_levels_weekend_matches_monday(self):
        monday = signals.levels(self.friday_bars(), today=date(2026, 11, 9))
        self.assertEqual(signals.levels(self.friday_bars(), today=date(2026, 11, 7)), monday)
        self.assertEqual(signals.levels(self.friday_bars(), today=date(2026, 11, 8)), monday)

    def test_levels_midweek_today_unchanged(self):
        bars = self.friday_bars() + [(date(2026, 11, 9), 1.0, 1.3, 1.15, 1.0),
                                     (date(2026, 11, 10), 1.0, 1.35, 1.12, 1.0)]
        base = signals.levels(bars)
        for day in (10, 11, 12, 13):
            self.assertEqual(signals.levels(bars, today=date(2026, 11, day)), base)
        self.assertEqual((base["week_high"], base["week_low"]), (1.60, 1.05))

    def test_analyze_on_monday_returns_friday_week_levels(self):
        # ~34 weekday bars ending Fri 2026-11-06; the previous week is Mon 11-02..Fri 11-06.
        end = date(2026, 11, 6)
        t0 = ts(2026, 9, 21)
        bars = []
        for i in range(47):
            t = t0 + i * DAY
            d = datetime.fromtimestamp(t, timezone.utc).date()
            if d.weekday() >= 5 or d > end:
                continue
            hi = 9.0 if d < date(2026, 11, 2) else 1.0 + (d.day % 7) * 0.01
            bars.append((t, 1.0, hi, 0.5 if d < date(2026, 11, 2) else 0.9, 1.0))
        wk = [b for b in bars if date(2026, 11, 2) <= datetime.fromtimestamp(
            b[0], timezone.utc).date() <= end]
        s = data.Series(bars=bars, gmtoffset=0)
        r = signals.analyze("X", "X", s, utc(2026, 11, 9, 7))  # Monday morning
        self.assertEqual(r["last_bar_date"], "2026-11-06")
        self.assertEqual(r["levels"]["week_high"], max(b[2] for b in wk))
        self.assertEqual(r["levels"]["week_low"], 0.9)


class TestAsiaRange(unittest.TestCase):
    def hourly(self):
        rows = []
        # previous day bars must be ignored entirely
        rows.append((ts(2026, 11, 12, 23), 1, 9.0, 0.1, 1))
        # asia hours 00..06 -> highs 1.1.., lows 1.0..
        for h in range(0, 7):
            rows.append((ts(2026, 11, 13, h), 1.0, 1.10 + h * 0.01, 1.00 + h * 0.001, 1.0))
        # 07:00 onward is not Asia but counts for the day range
        rows.append((ts(2026, 11, 13, 7), 1.0, 1.50, 0.90, 1.0))
        rows.append((ts(2026, 11, 13, 8), 1.0, 1.20, 0.95, 1.0))
        # a bar after "now" must be ignored
        rows.append((ts(2026, 11, 13, 12), 1.0, 7.0, 0.01, 1.0))
        return data.Series(bars=rows, gmtoffset=0)

    def test_asia_range_uses_only_00_to_07_utc(self):
        r = signals.asia_range(self.hourly(), utc(2026, 11, 13, 9, 30))
        self.assertAlmostEqual(r["asia_high"], 1.16)
        self.assertAlmostEqual(r["asia_low"], 1.00)
        self.assertAlmostEqual(r["day_high"], 1.50)
        self.assertAlmostEqual(r["day_low"], 0.90)

    def test_asia_range_none_without_bars_today(self):
        s = data.Series(bars=[(ts(2026, 11, 12, 3), 1, 2, 0.5, 1)], gmtoffset=0)
        self.assertIsNone(signals.asia_range(s, utc(2026, 11, 13, 9)))


class TestAnalyze(unittest.TestCase):
    def test_analyze_returns_none_under_30_sessions(self):
        s = data.Series(bars=flat_bars(29), gmtoffset=0)
        self.assertIsNone(signals.analyze("X", "X", s, utc(2026, 12, 31)))
        # 30 bars but the last is today's partial bar -> only 29 complete
        s30 = data.Series(bars=flat_bars(30, start=date(2026, 10, 1)), gmtoffset=0)
        self.assertIsNone(signals.analyze("X", "X", s30, utc(2026, 10, 30, 12)))

    def test_analyze_shape_on_30_sessions(self):
        s = data.Series(bars=flat_bars(30, start=date(2026, 10, 1)), gmtoffset=0)
        r = signals.analyze("EURUSD=X", "EUR/USD", s, utc(2026, 11, 5))
        self.assertEqual(set(r), {"symbol", "name", "last", "rsi", "atr_pct", "trend",
                                  "setups", "levels", "last_bar_date"})
        self.assertEqual(r["symbol"], "EURUSD=X")
        self.assertEqual(r["last"], 1.0)
        self.assertAlmostEqual(r["atr_pct"], 100.0)
        self.assertIsNone(r["trend"])
        self.assertEqual(r["last_bar_date"], "2026-10-30")
        self.assertEqual(r["setups"], [])

    def test_analyze_real_fixture_never_counts_partial_bar(self):
        with open(os.path.join(FIX, "eurusd_1d.json"), encoding="utf-8") as f:
            s = data.parse_chart(f.read(), "EURUSD=X")
        now = datetime.fromtimestamp(s.bars[-1][0], timezone.utc)
        r = signals.analyze("EURUSD=X", "EUR/USD", s, now)
        self.assertIsNotNone(r)
        self.assertLess(date.fromisoformat(r["last_bar_date"]), now.date())
        self.assertIn(r["trend"], ("up", "down", "mixed"))


if __name__ == "__main__":
    unittest.main()
