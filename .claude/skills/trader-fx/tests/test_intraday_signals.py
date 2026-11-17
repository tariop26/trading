import _path  # noqa
import unittest

import config
import intraday_signals as S
from intraday_helpers import make_bars, utc


def flat(n, price=1.1):
    return make_bars(utc(2026, 11, 16, 8), [(price, price, price, price)] * n)


class ConstantsTests(unittest.TestCase):
    def test_bar_and_families(self):
        self.assertEqual(S.BAR_S, 900)
        self.assertEqual(S.FAMILIES, config.INTRADAY_FAMILIES)


class ClosedBarsTests(unittest.TestCase):
    def test_drops_the_running_bar(self):
        bars = flat(4)  # 08:00, 08:15, 08:30, 08:45
        # at 08:50 the 08:45 bar (ends 09:00) is still running
        got = S.closed_bars(bars, utc(2026, 11, 16, 8, 50))
        self.assertEqual([b[0] for b in got], [b[0] for b in bars[:3]])
        # exactly at 09:00 it is closed (ts + 900 <= now)
        got = S.closed_bars(bars, utc(2026, 11, 16, 9, 0))
        self.assertEqual(len(got), 4)

    def test_sorts_unordered_timestamps(self):
        bars = flat(4)
        shuffled = [bars[2], bars[0], bars[3], bars[1]]
        got = S.closed_bars(shuffled, utc(2026, 11, 16, 12))
        self.assertEqual(got, bars)

    def test_removes_duplicate_keeping_last(self):
        bars = flat(3)
        dup = (bars[1][0], 9.0, 9.0, 9.0, 9.0)
        got = S.closed_bars(bars[:2] + [dup] + bars[2:], utc(2026, 11, 16, 12))
        self.assertEqual(len(got), 3)
        self.assertEqual(got[1], dup)
        self.assertEqual([b[0] for b in got], [b[0] for b in bars])

    def test_skips_malformed_entries(self):
        bars = flat(2)
        junk = [("x", 1, 1, 1, 1), (1, 2, 3), None, bars[0][:4]]
        got = S.closed_bars(junk + bars, utc(2026, 11, 16, 12))
        self.assertEqual(got, bars)

    def test_empty(self):
        self.assertEqual(S.closed_bars([], utc(2026, 11, 16, 12)), [])


class AtrTests(unittest.TestCase):
    def test_none_under_15_bars(self):
        bars = flat(20)
        self.assertIsNone(S.atr_bars(bars, 13))  # 14 bars
        self.assertIsNotNone(S.atr_bars(bars, 14))  # 15 bars

    def test_flat_series_is_zero(self):
        self.assertEqual(S.atr_bars(flat(30), 29), 0.0)

    def test_constant_range_and_wilder_smoothing(self):
        # every bar spans 0.002 around a constant close: TR = 0.002 each time
        bars = make_bars(utc(2026, 11, 16, 8), [(1.1, 1.101, 1.099, 1.1)] * 20)
        self.assertAlmostEqual(S.atr_bars(bars, 19), 0.002, places=9)
        # a wide bar after the seed window is smoothed in as (a * 13 + x) / 14
        ohlc = [(1.1, 1.101, 1.099, 1.1)] * 20
        ohlc[16] = (1.1, 1.116, 1.099, 1.1)  # TR = 0.017
        bars = make_bars(utc(2026, 11, 16, 8), ohlc)
        a = 0.002  # seed: mean of TRs of bars 1..14
        a = (a * 13 + 0.002) / 14  # bar 15
        a = (a * 13 + 0.017) / 14  # bar 16
        for _ in range(3):  # bars 17..19
            a = (a * 13 + 0.002) / 14
        self.assertAlmostEqual(S.atr_bars(bars, 19), a, places=9)

    def test_uses_gaps_from_previous_close(self):
        ohlc = [(1.1, 1.1, 1.1, 1.1)] * 14 + [(1.2, 1.2, 1.2, 1.2)]
        bars = make_bars(utc(2026, 11, 16, 8), ohlc)
        # 15 bars give 14 true ranges: thirteen 0 and the 0.1 gap (bar 14, flat bar
        # whose range is 0 but whose distance to the previous close is 0.1)
        self.assertAlmostEqual(S.atr_bars(bars, 14), 0.1 / 14, places=9)


class BollingerTests(unittest.TestCase):
    def test_none_when_short(self):
        bars = make_bars(utc(2026, 11, 16, 8), [(1, 1, 1, c) for c in range(1, 20)])
        self.assertIsNone(S.bollinger(bars, 18, 20, 2.0))  # 19 bars, period 20
        self.assertIsNotNone(S.bollinger(bars, 18, 19, 2.0))

    def test_none_on_flat_series(self):
        self.assertIsNone(S.bollinger(flat(30), 29, 20, 2.0))

    def test_none_on_flat_series_whatever_the_price_and_period(self):
        for price in (1.0834, 0.7123, 149.37, 1.1):
            for period in (7, 13, 20, 21):
                self.assertIsNone(S.bollinger(flat(40, price), 39, period, 2.0), (price, period))

    def test_mid_is_mean_and_bands_use_population_sd(self):
        closes = [1.0, 2.0, 3.0, 4.0, 5.0]
        bars = make_bars(utc(2026, 11, 16, 8), [(c, c, c, c) for c in closes])
        mid, up, lo = S.bollinger(bars, 4, 5, 2.0)
        self.assertAlmostEqual(mid, 3.0)
        sd = 2 ** 0.5  # population variance = 2
        self.assertAlmostEqual(up, 3.0 + 2 * sd)
        self.assertAlmostEqual(lo, 3.0 - 2 * sd)

    def test_window_ends_at_index(self):
        closes = [10.0, 1.0, 2.0, 3.0, 99.0]
        bars = make_bars(utc(2026, 11, 16, 8), [(c, c, c, c) for c in closes])
        mid, _, _ = S.bollinger(bars, 3, 3, 2.0)  # closes 1, 2, 3
        self.assertAlmostEqual(mid, 2.0)


class SignalParamsTests(unittest.TestCase):
    def test_merges_plan_values(self):
        cfg = {"intraday": {"a": 1, "b": 2}, "plan": {"stop_atr_mult": 1.5, "target_r": 2.0}}
        got = S.signal_params(cfg)
        self.assertEqual(got, {"a": 1, "b": 2, "stop_atr_mult": 1.5, "target_r": 2.0})
        self.assertNotIn("stop_atr_mult", cfg["intraday"])  # input not mutated


PARAMS = {"range_minutes": 30, "break_window_hours": 3}
LONDON_RANGE = [(1.1000, 1.1010, 1.0990, 1.1005), (1.1005, 1.1012, 1.0995, 1.1000)]  # 08:00, 08:15


def ts(y, m, d, h, mi=0):
    return int(utc(y, m, d, h, mi).timestamp())


def london_bars(*after):
    """The two range bars (08:00-08:30 UTC, 2026-11-16) then `after` OHLC tuples."""
    return make_bars(utc(2026, 11, 16, 8), LONDON_RANGE + list(after))


def inside(c=1.1000):
    return (c, c, c, c)


def london_range(bars):
    got = [r for r in S.session_ranges(bars, utc(2026, 11, 16, 16), PARAMS) if r["name"] == "Londres"]
    return got


class SessionRangesTests(unittest.TestCase):
    def test_london_range_values(self):
        bars = london_bars(inside())
        (r,) = london_range(bars)
        self.assertEqual(r["high"], 1.1012)
        self.assertEqual(r["low"], 1.0990)
        self.assertEqual(r["day"], "2026-11-16")
        self.assertEqual(r["start"], ts(2026, 11, 16, 8))
        self.assertEqual(r["end"], ts(2026, 11, 16, 8, 30))

    def test_range_excludes_bars_from_end_onwards(self):
        bars = london_bars((1.1, 1.2, 1.0, 1.1))  # 08:30 bar is outside [08:00, 08:30)
        (r,) = london_range(bars)
        self.assertEqual((r["high"], r["low"]), (1.1012, 1.0990))

    def test_asia_range_uses_00_to_07_utc(self):
        # 28 bars from 00:00 (to 06:45) plus the 07:00 bar, which is outside Asie
        ohlc = [(1.1, 1.1, 1.1, 1.1)] * 28
        ohlc[5] = (1.1, 1.1050, 1.1, 1.1)   # 01:15 high
        ohlc[20] = (1.1, 1.1, 1.0950, 1.1)  # 05:00 low
        ohlc.append((1.1, 1.3, 0.9, 1.1))   # 07:00, excluded
        bars = make_bars(utc(2026, 11, 16, 0), ohlc)
        got = S.session_ranges(bars, utc(2026, 11, 16, 8), PARAMS)
        asia = [r for r in got if r["name"] == "Asie"]
        self.assertEqual(len(asia), 1)
        a = asia[0]
        self.assertEqual((a["high"], a["low"]), (1.1050, 1.0950))
        self.assertEqual(a["start"], ts(2026, 11, 16, 0))
        self.assertEqual(a["end"], ts(2026, 11, 16, 7))
        self.assertEqual(a["day"], "2026-11-16")

    def test_names_in_order_and_empty_ranges_omitted(self):
        self.assertEqual(S.session_ranges([], utc(2026, 11, 16, 16), PARAMS), [])
        bars = london_bars(inside())
        got = S.session_ranges(bars, utc(2026, 11, 16, 16), PARAMS)
        self.assertEqual([r["name"] for r in got], ["Londres"])
        # New York 08:00 local = 13:00 UTC in November
        ny = make_bars(utc(2026, 11, 16, 13), [inside()])
        got = S.session_ranges(bars + ny, utc(2026, 11, 16, 16), PARAMS)
        self.assertEqual([r["name"] for r in got], ["Londres", "New York"])
        asia = make_bars(utc(2026, 11, 16, 0), [inside()])
        got = S.session_ranges(asia + bars + ny, utc(2026, 11, 16, 16), PARAMS)
        self.assertEqual([r["name"] for r in got], ["Asie", "Londres", "New York"])

    def test_ranges_follow_dst(self):
        # summer: London 08:00 BST = 07:00 UTC
        bars = make_bars(utc(2026, 7, 15, 7), LONDON_RANGE)
        (r,) = [r for r in S.session_ranges(bars, utc(2026, 7, 15, 12), PARAMS) if r["name"] == "Londres"]
        self.assertEqual(r["start"], ts(2026, 7, 15, 7))
        self.assertEqual(r["end"], ts(2026, 7, 15, 7, 30))
        self.assertEqual((r["high"], r["low"]), (1.1012, 1.0990))
        # the winter-hour bars (08:00 UTC) are not in the summer London range
        late = make_bars(utc(2026, 7, 15, 8), LONDON_RANGE)
        self.assertEqual([r for r in S.session_ranges(late, utc(2026, 7, 15, 12), PARAMS)
                          if r["name"] == "Londres"], [])
        # 2026-10-28: US is still on EDT (until Nov 1), London back on GMT (since Oct 25)
        # New York 08:00 EDT = 12:00 UTC
        ny = make_bars(utc(2026, 10, 28, 12), LONDON_RANGE)
        (r,) = [r for r in S.session_ranges(ny, utc(2026, 10, 28, 16), PARAMS) if r["name"] == "New York"]
        self.assertEqual(r["start"], ts(2026, 10, 28, 12))
        self.assertEqual(r["end"], ts(2026, 10, 28, 12, 30))
        # and London that day is 08:00 UTC (GMT)
        ldn = make_bars(utc(2026, 10, 28, 8), LONDON_RANGE)
        (r,) = [r for r in S.session_ranges(ldn, utc(2026, 10, 28, 16), PARAMS) if r["name"] == "Londres"]
        self.assertEqual(r["start"], ts(2026, 10, 28, 8))

    def test_range_minutes_param(self):
        bars = london_bars((1.1, 1.1020, 1.1, 1.1))  # 08:30 bar joins a 45-minute range
        (r,) = [r for r in S.session_ranges(bars, utc(2026, 11, 16, 16),
                                            {"range_minutes": 45, "break_window_hours": 3})
                if r["name"] == "Londres"]
        self.assertEqual(r["high"], 1.1020)
        self.assertEqual(r["end"], ts(2026, 11, 16, 8, 45))


class SessionBreakTests(unittest.TestCase):
    def sig(self, bars, i):
        ranges = S.session_ranges(bars, utc(2026, 11, 16, 16), PARAMS)
        return S.session_break(bars, i, ranges, PARAMS)

    def test_break_up_on_first_close_outside(self):
        bars = london_bars((1.1005, 1.1022, 1.1005, 1.1020))  # 08:30
        s = self.sig(bars, 2)
        self.assertEqual(s, {"family": "session_break", "side": "haussier", "i": 2,
                             "stop_raw": 1.0990, "target_raw": None, "detail": "Londres"})

    def test_second_close_outside_gives_no_signal(self):
        bars = london_bars((1.1005, 1.1022, 1.1005, 1.1020), (1.1020, 1.1027, 1.1020, 1.1025))
        self.assertIsNotNone(self.sig(bars, 2))
        self.assertIsNone(self.sig(bars, 3))

    def test_close_inside_gives_none(self):
        bars = london_bars(inside(1.1005))
        self.assertIsNone(self.sig(bars, 2))
        self.assertIsNone(self.sig(bars, 1))  # a range bar itself never breaks

    def test_close_equal_to_edge_is_not_outside(self):
        bars = london_bars((1.1, 1.1012, 1.1, 1.1012), (1.1, 1.0990, 1.0990, 1.0990))
        self.assertIsNone(self.sig(bars, 2))
        self.assertIsNone(self.sig(bars, 3))

    def test_break_down_mirror(self):
        bars = london_bars((1.0995, 1.0996, 1.0978, 1.0980))
        s = self.sig(bars, 2)
        self.assertEqual(s["side"], "baissier")
        self.assertEqual(s["stop_raw"], 1.1012)
        self.assertIsNone(s["target_raw"])
        self.assertEqual(s["detail"], "Londres")

    def test_inside_bar_then_break_still_signals(self):
        bars = london_bars(inside(1.1005), (1.1005, 1.1022, 1.1005, 1.1020))
        self.assertIsNone(self.sig(bars, 2))
        self.assertEqual(self.sig(bars, 3)["side"], "haussier")

    def test_opposite_side_after_first_break_signals(self):
        bars = london_bars((1.1005, 1.1022, 1.1005, 1.1020), (1.1020, 1.1020, 1.0980, 1.0985))
        self.assertEqual(self.sig(bars, 2)["side"], "haussier")
        s = self.sig(bars, 3)
        self.assertEqual(s["side"], "baissier")
        self.assertEqual(s["stop_raw"], 1.1012)

    def test_window_closes_after_three_hours(self):
        # inside closes 08:30 .. 11:00, then 11:15 (last bar ending by 11:30) and 11:30
        n_inside = 11  # 08:30, 08:45, ... 11:00
        bars = london_bars(*([inside(1.1005)] * n_inside),
                           (1.1005, 1.1022, 1.1005, 1.1020),   # 11:15
                           (1.1020, 1.1030, 1.1020, 1.1025))   # 11:30
        self.assertEqual(bars[2 + n_inside][0], ts(2026, 11, 16, 11, 15))
        self.assertEqual(self.sig(bars, 2 + n_inside)["side"], "haussier")
        broken_later = london_bars(*([inside(1.1005)] * (n_inside + 1)),
                                   (1.1005, 1.1022, 1.1005, 1.1020))  # 11:30 breaks, too late
        self.assertEqual(broken_later[2 + n_inside + 1][0], ts(2026, 11, 16, 11, 30))
        self.assertIsNone(self.sig(broken_later, 2 + n_inside + 1))

    def test_out_of_range_index_and_no_ranges(self):
        bars = london_bars((1.1005, 1.1022, 1.1005, 1.1020))
        ranges = S.session_ranges(bars, utc(2026, 11, 16, 16), PARAMS)
        self.assertIsNone(S.session_break(bars, 99, ranges, PARAMS))
        self.assertIsNone(S.session_break(bars, -1, ranges, PARAMS))
        self.assertIsNone(S.session_break(bars, 2, [], PARAMS))
        self.assertIsNone(S.session_break([], 0, [], PARAMS))

    def test_latest_range_wins_when_several_trigger(self):
        # Asie 00:00-07:00 (1.1000 flat), Londres 08:00-08:30 (1.1000 flat); a bar at
        # 08:30 closing above both breaks Londres; Asie broke earlier at 07:00 closes
        # only if none was closed outside before, so keep Asie unbroken with inside bars.
        asia = make_bars(utc(2026, 11, 16, 0), [(1.1, 1.1, 1.1, 1.1)] * 28)
        gap = make_bars(utc(2026, 11, 16, 7), [(1.1, 1.1, 1.1, 1.1)] * 4)  # 07:00-07:45 inside
        lon = make_bars(utc(2026, 11, 16, 8), [(1.1, 1.1, 1.1, 1.1)] * 2)
        brk = make_bars(utc(2026, 11, 16, 8, 30), [(1.1, 1.103, 1.1, 1.102)])
        bars = asia + gap + lon + brk
        ranges = S.session_ranges(bars, utc(2026, 11, 16, 16), PARAMS)
        self.assertEqual([r["name"] for r in ranges], ["Asie", "Londres"])
        s = S.session_break(bars, len(bars) - 1, ranges, PARAMS)
        self.assertEqual(s["detail"], "Londres")
        self.assertEqual(s["i"], len(bars) - 1)


if __name__ == "__main__":
    unittest.main()
