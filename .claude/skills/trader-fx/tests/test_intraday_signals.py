import _path  # noqa
import unittest

import config
import signals
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


SIG_PARAMS = {"bb_period": 20, "bb_std": 2.0, "rsi_period": 14, "rsi_low": 30, "rsi_high": 70,
              "stop_atr_mult": 1.5}


def closes_to_bars(closes, spread=0.0005):
    """Bars closing on `closes`, each with a high/low `spread` around open/close."""
    ohlc = []
    prev = closes[0]
    for c in closes:
        ohlc.append((prev, max(prev, c) + spread, min(prev, c) - spread, c))
        prev = c
    return make_bars(utc(2026, 11, 16, 8), ohlc)


def calm(n=19):
    """n quiet closes alternating 1.1000 / 1.1002."""
    return [1.1000 + 0.0002 * (k % 2) for k in range(n)]


class BbReturnTests(unittest.TestCase):
    def bands(self, bars, i):
        return S.bollinger(bars, i, 20, 2.0)

    def test_bb_return_bearish(self):
        bars = closes_to_bars(calm() + [1.1030, 1.1010])  # spike at 19, back inside at 20
        i = len(bars) - 1
        self.assertGreater(bars[i - 1][4], self.bands(bars, i - 1)[1])  # premise: above upper
        self.assertLessEqual(bars[i][4], self.bands(bars, i)[1])        # premise: back inside
        s = S.bb_return(bars, i, SIG_PARAMS)
        self.assertEqual(s, {"family": "bb_return", "side": "baissier", "i": i,
                             "stop_raw": bars[i - 1][2], "target_raw": self.bands(bars, i)[0],
                             "detail": ""})
        self.assertEqual(s["stop_raw"], bars[i - 1][2])

    def test_bb_return_bullish_mirror(self):
        bars = closes_to_bars(calm() + [1.0970, 1.0990])
        i = len(bars) - 1
        self.assertLess(bars[i - 1][4], self.bands(bars, i - 1)[2])  # premise: below lower
        self.assertGreaterEqual(bars[i][4], self.bands(bars, i)[2])  # premise: back inside
        s = S.bb_return(bars, i, SIG_PARAMS)
        self.assertEqual(s, {"family": "bb_return", "side": "haussier", "i": i,
                             "stop_raw": bars[i - 1][3], "target_raw": self.bands(bars, i)[0],
                             "detail": ""})

    def test_bb_stop_is_the_extreme_of_the_previous_bar(self):
        bars = closes_to_bars(calm() + [1.1030, 1.1010])
        i = len(bars) - 1
        bars[i - 1] = bars[i - 1][:2] + (1.1100,) + bars[i - 1][3:]  # wick above the close
        self.assertEqual(S.bb_return(bars, i, SIG_PARAMS)["stop_raw"], 1.1100)

    def test_bb_close_on_the_band_counts_as_back_inside(self):
        bars = closes_to_bars(calm() + [1.1030, 1.1010])
        i = len(bars) - 1
        lo, hi = 1.1000, 1.1030  # bisect the last close onto its own upper band
        for _ in range(100):
            mid = (lo + hi) / 2
            bars[i] = bars[i][:4] + (mid,)
            if mid <= self.bands(bars, i)[1]:
                lo = mid
            else:
                hi = mid
        bars[i] = bars[i][:4] + (lo,)
        self.assertLessEqual(bars[i][4], self.bands(bars, i)[1])
        self.assertAlmostEqual(bars[i][4], self.bands(bars, i)[1], places=9)  # on the band
        self.assertEqual(S.bb_return(bars, i, SIG_PARAMS)["side"], "baissier")

    def test_bb_still_outside_gives_none(self):
        bars = closes_to_bars(calm() + [1.1030, 1.1028])
        i = len(bars) - 1
        self.assertGreater(bars[i - 1][4], self.bands(bars, i - 1)[1])
        self.assertGreater(bars[i][4], self.bands(bars, i)[1])  # premise: still outside
        self.assertIsNone(S.bb_return(bars, i, SIG_PARAMS))
        bars = closes_to_bars(calm() + [1.0970, 1.0972])
        self.assertLess(bars[i - 1][4], self.bands(bars, i - 1)[2])
        self.assertLess(bars[i][4], self.bands(bars, i)[2])
        self.assertIsNone(S.bb_return(bars, i, SIG_PARAMS))

    def test_bb_previous_bar_inside_gives_none(self):
        bars = closes_to_bars(calm() + [1.1001, 1.1000])
        i = len(bars) - 1
        self.assertLessEqual(bars[i - 1][4], self.bands(bars, i - 1)[1])
        self.assertIsNone(S.bb_return(bars, i, SIG_PARAMS))

    def test_bb_short_or_flat_series_gives_none(self):
        # 20 bars with the spike on bar 19: the window of bar 18 is incomplete
        bars = closes_to_bars(calm() + [1.1030])
        self.assertIsNone(S.bollinger(bars, len(bars) - 2, 20, 2.0))  # premise: short
        for i in (-1, 0, 1, 5, len(bars) - 1):
            self.assertIsNone(S.bb_return(bars, i, SIG_PARAMS))
        self.assertIsNone(S.bb_return([], 0, SIG_PARAMS))
        # flat series: sd 0, bands undefined
        f = flat(40)
        for i in (1, 20, 21, 39):
            self.assertIsNone(S.bb_return(f, i, SIG_PARAMS))


class RsiExitTests(unittest.TestCase):
    def rsis(self, bars, i):
        closes = [b[4] for b in bars]
        return signals.rsi(closes[:i], 14), signals.rsi(closes[:i + 1], 14)

    def test_rsi_exit_bullish(self):
        closes = [1.1000 - 0.001 * k for k in range(20)] + [1.0910]  # fall, then a rebound
        bars = closes_to_bars(closes)
        i = len(bars) - 1
        prev, now = self.rsis(bars, i)
        self.assertLess(prev, 30)       # premise
        self.assertGreaterEqual(now, 30)
        s = S.rsi_exit(bars, i, SIG_PARAMS)
        atr = S.atr_bars(bars, i)
        self.assertGreater(atr, 0)
        self.assertEqual(s["family"], "rsi_exit")
        self.assertEqual(s["side"], "haussier")
        self.assertEqual(s["i"], i)
        self.assertAlmostEqual(s["stop_raw"], closes[-1] - 1.5 * atr, places=12)
        self.assertIsNone(s["target_raw"])
        self.assertEqual(s["detail"], "")

    def test_rsi_exit_bearish_mirror(self):
        closes = [1.1000 + 0.001 * k for k in range(20)] + [1.1090]  # rise, then a drop
        bars = closes_to_bars(closes)
        i = len(bars) - 1
        prev, now = self.rsis(bars, i)
        self.assertGreater(prev, 70)    # premise
        self.assertLessEqual(now, 70)
        s = S.rsi_exit(bars, i, SIG_PARAMS)
        atr = S.atr_bars(bars, i)
        self.assertEqual(s["side"], "baissier")
        self.assertEqual(s["i"], i)
        self.assertAlmostEqual(s["stop_raw"], closes[-1] + 1.5 * atr, places=12)
        self.assertIsNone(s["target_raw"])

    def test_rsi_staying_in_zone_gives_none(self):
        down = closes_to_bars([1.1000 - 0.001 * k for k in range(20)] + [1.0805])  # still falling
        prev, now = self.rsis(down, len(down) - 1)
        self.assertLess(prev, 30)
        self.assertLess(now, 30)        # premise: no exit
        self.assertIsNone(S.rsi_exit(down, len(down) - 1, SIG_PARAMS))
        up = closes_to_bars([1.1000 + 0.001 * k for k in range(20)] + [1.1205])
        prev, now = self.rsis(up, len(up) - 1)
        self.assertGreater(prev, 70)
        self.assertGreater(now, 70)
        self.assertIsNone(S.rsi_exit(up, len(up) - 1, SIG_PARAMS))

    def test_rsi_short_series_gives_none(self):
        # rsi_period + 2 = 16 closes are needed; 15 are not enough
        bars = closes_to_bars([1.1000 - 0.001 * k for k in range(14)] + [1.0970])
        self.assertEqual(len(bars), 15)
        self.assertIsNone(signals.rsi([b[4] for b in bars[:14]], 14))  # premise: prev missing
        for i in (-1, 0, 1, 10, 13, 14):
            self.assertIsNone(S.rsi_exit(bars, i, SIG_PARAMS))
        self.assertIsNone(S.rsi_exit([], 0, SIG_PARAMS))
        # 16 closes are enough
        bars16 = closes_to_bars([1.1000 - 0.001 * k for k in range(15)] + [1.0960])
        self.assertEqual(len(bars16), 16)
        self.assertEqual(S.rsi_exit(bars16, 15, SIG_PARAMS)["side"], "haussier")

    def test_rsi_flat_series_gives_none(self):
        f = flat(40)
        closes = [b[4] for b in f]
        self.assertEqual(signals.rsi(closes, 14), 100.0)  # premise: constant RSI 100
        self.assertEqual(signals.rsi(closes[:-1], 14), 100.0)
        for i in (0, 15, 20, 39):
            self.assertIsNone(S.rsi_exit(f, i, SIG_PARAMS))

    def test_rsi_exit_none_when_atr_unavailable_or_zero(self):
        bars = closes_to_bars([1.1000 - 0.001 * k for k in range(20)] + [1.0910])
        i = len(bars) - 1
        self.assertIsNotNone(S.rsi_exit(bars, i, SIG_PARAMS))
        orig = S.atr_bars
        try:
            S.atr_bars = lambda b, k, n=14: None
            self.assertIsNone(S.rsi_exit(bars, i, SIG_PARAMS))
            S.atr_bars = lambda b, k, n=14: 0.0
            self.assertIsNone(S.rsi_exit(bars, i, SIG_PARAMS))
        finally:
            S.atr_bars = orig


ENG = {"engulfing_min_prior": 3, "stop_atr_mult": 1.5}


def obars(rows):
    """Bars from (o, h, l, c) rows, 15 minutes apart from 08:00 UTC."""
    return make_bars(utc(2026, 11, 16, 8), rows)


# i - 3 .. i - 1 bearish (bar 0 is bullish and outside the run), bar 4 a bullish engulfing
# whose low (1.1000) is below the low of bar 3 (1.1005): the stop tells i from i - 1.
BULL_ENG = [
    (1.1000, 1.1010, 1.0995, 1.1008),
    (1.1030, 1.1032, 1.1018, 1.1025),
    (1.1025, 1.1027, 1.1012, 1.1020),
    (1.1020, 1.1022, 1.1005, 1.1010),
    (1.1008, 1.1030, 1.1000, 1.1025),
]
# mirror: three bullish bars then a bearish engulfing whose high (1.1020) is above bar 3's.
BEAR_ENG = [
    (1.1010, 1.1015, 1.1000, 1.1002),
    (1.0990, 1.1002, 1.0988, 1.0995),
    (1.0995, 1.1008, 1.0993, 1.1003),
    (1.1003, 1.1015, 1.1001, 1.1012),
    (1.1015, 1.1020, 1.0990, 1.1000),
]


class SignalHelperTests(unittest.TestCase):
    def test_signal_builds_the_standard_dict(self):
        self.assertEqual(S._signal("engulfing", "haussier", 4, 1.1, None),
                         {"family": "engulfing", "side": "haussier", "i": 4,
                          "stop_raw": 1.1, "target_raw": None, "detail": ""})
        self.assertEqual(S._signal("session_break", "baissier", 2, 1.2, 1.0, "Londres"),
                         {"family": "session_break", "side": "baissier", "i": 2,
                          "stop_raw": 1.2, "target_raw": 1.0, "detail": "Londres"})


class EngulfingTests(unittest.TestCase):
    def test_engulfing_bullish(self):
        bars = obars(BULL_ENG)
        i = 4
        for k in (1, 2, 3):  # premise: the three prior bars are bearish (c < o)
            self.assertLess(bars[k][4], bars[k][1])
        self.assertGreater(bars[i][4], bars[i][1])  # premise: bar i is bullish
        self.assertEqual(S.engulfing(bars, i, ENG),
                         {"family": "engulfing", "side": "haussier", "i": i,
                          "stop_raw": 1.1000, "target_raw": None, "detail": ""})
        self.assertNotEqual(bars[i][3], bars[i - 1][3])  # the stop discriminates i from i - 1

    def test_engulfing_bearish(self):
        bars = obars(BEAR_ENG)
        i = 4
        self.assertNotEqual(bars[i][2], bars[i - 1][2])
        s = S.engulfing(bars, i, ENG)
        self.assertEqual(s, {"family": "engulfing", "side": "baissier", "i": i,
                             "stop_raw": 1.1020, "target_raw": None, "detail": ""})

    def test_engulfing_needs_three_prior_opposite_bars(self):
        # only two bearish bars before the engulfing bar: i < k
        two = obars(BULL_ENG[2:5])
        self.assertIsNone(S.engulfing(two, 2, ENG))
        # four bars, but the oldest of the three required prior bars (bar 0) is bullish
        mixed = obars([BULL_ENG[0], BULL_ENG[2], BULL_ENG[3], BULL_ENG[4]])
        self.assertGreater(mixed[0][4], mixed[0][1])  # premise: bar 0 is bullish
        self.assertIsNone(S.engulfing(mixed, 3, ENG))
        # control: with a third bearish bar the very same engulfing bar signals
        three = obars(BULL_ENG[1:5])
        self.assertEqual(S.engulfing(three, 3, ENG)["side"], "haussier")
        # the threshold comes from params: two prior bars suffice when it is 2
        self.assertEqual(S.engulfing(two, 2, dict(ENG, engulfing_min_prior=2))["side"], "haussier")

    def test_engulfing_doji_breaks_the_run(self):
        rows = list(BULL_ENG)
        rows[2] = (1.1025, 1.1027, 1.1012, 1.1025)  # doji: close == open
        bars = obars(rows)
        self.assertEqual(bars[2][4], bars[2][1])  # premise
        self.assertIsNone(S.engulfing(bars, 4, ENG))
        rows = list(BULL_ENG)
        rows[4] = (1.1025, 1.1030, 1.1000, 1.1025)  # the last bar is a doji: neither side
        self.assertIsNone(S.engulfing(obars(rows), 4, ENG))

    def test_engulfing_body_must_contain_previous_body(self):
        base = obars(BULL_ENG)
        self.assertIsNotNone(S.engulfing(base, 4, ENG))  # premise: the pattern signals
        prev = base[3]
        self.assertEqual((min(prev[1], prev[4]), max(prev[1], prev[4])), (1.1010, 1.1020))

        def with_last(o, c):
            rows = list(BULL_ENG)
            rows[4] = (o, 1.1030, 1.1000, c)
            return obars(rows)

        self.assertIsNone(S.engulfing(with_last(1.1012, 1.1025), 4, ENG))  # body starts above
        self.assertIsNone(S.engulfing(with_last(1.1008, 1.1018), 4, ENG))  # body ends below
        self.assertEqual(S.engulfing(with_last(1.1010, 1.1020), 4, ENG)["side"],
                         "haussier")  # equal edges still contain
        # mirror on the bearish side
        prev = obars(BEAR_ENG)[3]
        self.assertEqual((min(prev[1], prev[4]), max(prev[1], prev[4])), (1.1003, 1.1012))
        brows = list(BEAR_ENG)
        brows[4] = (1.1015, 1.1020, 1.0990, 1.1003)  # equal lower edge still contains
        self.assertEqual(S.engulfing(obars(brows), 4, ENG)["side"], "baissier")
        brows[4] = (1.1015, 1.1020, 1.0990, 1.1005)  # body ends above the previous low edge
        self.assertIsNone(S.engulfing(obars(brows), 4, ENG))
        brows[4] = (1.1010, 1.1020, 1.0990, 1.1000)  # body starts below the previous top
        self.assertIsNone(S.engulfing(obars(brows), 4, ENG))

    def test_engulfing_same_colour_gives_none(self):
        rows = list(BULL_ENG)
        rows[4] = (1.1025, 1.1030, 1.1000, 1.1008)  # bearish last bar after a bearish run
        self.assertIsNone(S.engulfing(obars(rows), 4, ENG))

    def test_engulfing_out_of_range_index(self):
        bars = obars(BULL_ENG)
        for i in (-1, 5, 99):
            self.assertIsNone(S.engulfing(bars, i, ENG))
        self.assertIsNone(S.engulfing([], 0, ENG))


def hlbars(rows):
    """Bars from (high, low[, close]) rows; open and (default) close at the mid."""
    out = []
    for r in rows:
        h, l = r[0], r[1]
        mid = (h + l) / 2
        out.append((mid, h, l, r[2] if len(r) > 2 else mid))
    return obars(out)


def fractals(bars, i):
    """Independent re-statement of the confirmed Williams fractals at bar i (k <= i - 3,
    at most 50 bars back): (indices of fractal highs, indices of fractal lows)."""
    hs, ls = [], []
    for k in range(max(2, i - 50), i - 2):
        near = (k - 2, k - 1, k + 1, k + 2)
        if all(bars[k][2] > bars[j][2] for j in near):
            hs.append(k)
        if all(bars[k][3] < bars[j][3] for j in near):
            ls.append(k)
    return hs, ls


def mirror(bars, k=2.2):
    return [(b[0], k - b[1], k - b[3], k - b[2], k - b[4]) for b in bars]


# fractal high at 6 (1.1050), fractal low at 2 (1.0950), bar 9 closes above 1.1050
UP_H = [1.1010, 1.1010, 1.1010, 1.1020, 1.1030, 1.1040, 1.1050, 1.1030, 1.1020, 1.1060]
UP_L = [1.0990, 1.0980, 1.0950, 1.0985, 1.0990, 1.1000, 1.1010, 1.1000, 1.0995, 1.1020]


def up_bars():
    rows = list(zip(UP_H, UP_L))
    rows[9] = (1.1060, 1.1020, 1.1055)
    return hlbars(rows)


# older fractal high at 2 (1.1080), newer one at 5 (1.1060) broken by the close of bar 8;
# bar 9 then closes above the older level, which a fallback would wrongly accept
BRK_H = [1.1060, 1.1070, 1.1080, 1.1010, 1.1000, 1.1060, 1.1020, 1.1010, 1.1070, 1.1090]
BRK_L = [1.1000, 1.0990, 1.0970, 1.0990, 1.0995, 1.1000, 1.1000, 1.1005, 1.1010, 1.1060]


def brk_bars():
    rows = list(zip(BRK_H, BRK_L))
    rows[8] = (1.1070, 1.1010, 1.1065)
    rows[9] = (1.1090, 1.1060, 1.1085)
    return hlbars(rows)


def gap_bars():
    """Fractal high at 7 (1.0900); the only fractal low (index 2, 1.1050) lies ABOVE the
    close 1.0950 of bar 14, so the stop must come from the ATR."""
    rows = [(1.1210, 1.1110), (1.1200, 1.1100), (1.1190, 1.1050), (1.1100, 1.1060),
            (1.1090, 1.1070), (1.0885, 1.0870), (1.0880, 1.0860), (1.0900, 1.0850)]
    rows += [(1.0870 - 0.0005 * n, 1.0840 - 0.0005 * n) for n in range(6)]  # bars 8..13
    rows.append((1.0960, 1.0800, 1.0950))  # bar 14
    return hlbars(rows)


def rising_bars():
    """Rising lows (no fractal low), one spiking high at 10 (1.0980); bar 14 closes above."""
    rows = []
    for n in range(15):
        low = 1.0900 + 0.0002 * n
        rows.append((low + (0.006 if n == 10 else 0.002), low))
    rows[14] = (1.0990, 1.0900 + 0.0002 * 14, 1.0985)
    return hlbars(rows)


FRA = {"stop_atr_mult": 1.5}


class FractalBreakTests(unittest.TestCase):
    def test_fractal_break_up(self):
        bars = up_bars()
        self.assertEqual(fractals(bars, 9), ([6], [2]))  # premise
        self.assertEqual((bars[6][2], bars[2][3]), (1.1050, 1.0950))
        self.assertGreater(bars[9][4], 1.1050)
        s = S.fractal_break(bars, 9, FRA)
        self.assertEqual(s, {"family": "fractal_break", "side": "haussier", "i": 9,
                             "stop_raw": 1.0950, "target_raw": None, "detail": ""})
        for i in range(0, 9):  # nothing before the breaking bar
            self.assertIsNone(S.fractal_break(bars, i, FRA), i)

    def test_fractal_unconfirmed_is_ignored(self):
        rows = [(1.1000, 1.0990), (1.1010, 1.0980), (1.1020, 1.0950), (1.1030, 1.0985),
                (1.1040, 1.0990), (1.1020, 1.0990), (1.1060, 1.1000, 1.1055)]
        bars = hlbars(rows)
        hs, ls = fractals(bars, 6)
        self.assertEqual((hs, ls), ([], [2]))  # premise: a stop exists, no confirmed high
        # the peak at 4 beats 2, 3 and 5 but bar 6 (= 4 + 2) is higher: not a fractal yet
        self.assertTrue(all(bars[4][2] > bars[j][2] for j in (2, 3, 5)))
        self.assertGreater(bars[6][2], bars[4][2])
        self.assertGreater(bars[6][4], bars[4][2])  # the close is above that recent peak
        self.assertIsNone(S.fractal_break(bars, 6, FRA))

    def test_fractal_already_broken_gives_none(self):
        bars = brk_bars()
        self.assertEqual(fractals(bars, 9), ([2, 5], [2]))  # premise
        level = bars[5][2]
        self.assertEqual(level, 1.1060)
        # bar 8 is the first close above the latest fractal high: it signals
        self.assertGreater(bars[8][4], level)
        s8 = S.fractal_break(bars[:9], 8, FRA)
        self.assertEqual((s8["side"], s8["stop_raw"]), ("haussier", 1.0970))
        # bar 9 closes above it again: already broken, no signal ...
        self.assertGreater(bars[9][4], level)
        self.assertIsNone(S.fractal_break(bars, 9, FRA))
        # ... and no fallback on the older, never broken, fractal high of bar 2
        older = bars[2][2]
        self.assertGreater(bars[9][4], older)
        self.assertFalse(any(b[4] > older for b in bars[5:9]))

    def test_fractal_without_opposite_fractal_uses_atr_stop(self):
        bars = rising_bars()
        i = 14
        self.assertEqual(fractals(bars, i), ([10], []))  # premise: no fractal low
        self.assertGreater(bars[i][4], bars[10][2])
        atr = S.atr_bars(bars, i)
        self.assertGreater(atr, 0)
        s = S.fractal_break(bars, i, FRA)
        self.assertEqual((s["family"], s["side"], s["i"]), ("fractal_break", "haussier", i))
        self.assertAlmostEqual(s["stop_raw"], bars[i][4] - 1.5 * atr, places=12)
        self.assertIsNone(s["target_raw"])
        self.assertEqual(s["detail"], "")
        # no usable ATR: no signal
        orig = S.atr_bars
        try:
            S.atr_bars = lambda b, k, n=14: None
            self.assertIsNone(S.fractal_break(bars, i, FRA))
            S.atr_bars = lambda b, k, n=14: 0.0
            self.assertIsNone(S.fractal_break(bars, i, FRA))
        finally:
            S.atr_bars = orig

    def test_fractal_opposite_low_above_close_uses_atr_stop(self):
        bars = gap_bars()
        i = 14
        self.assertEqual(fractals(bars, i), ([7], [2]))  # premise
        self.assertGreater(bars[i][4], bars[7][2])
        self.assertGreater(bars[2][3], bars[i][4])  # the fractal low is above the close
        atr = S.atr_bars(bars, i)
        self.assertGreater(atr, 0)
        s = S.fractal_break(bars, i, FRA)
        self.assertEqual(s["side"], "haussier")
        self.assertAlmostEqual(s["stop_raw"], bars[i][4] - 1.5 * atr, places=12)

    def test_fractal_lookback_is_fifty_bars(self):
        rows = [(1.1000, 1.0990)] * 54
        rows[4] = (1.1100, 1.0990)   # fractal high at 4
        rows[14] = (1.1000, 1.0900)  # fractal low at 14
        brk = (1.1110, 1.1000, 1.1105)
        at_50 = hlbars(rows + [brk])           # i = 54: k = 4 = i - 50, still searched
        self.assertEqual(fractals(at_50, 54), ([4], [14]))
        s = S.fractal_break(at_50, 54, FRA)
        self.assertEqual((s["side"], s["stop_raw"]), ("haussier", 1.0900))
        at_51 = hlbars(rows + [(1.1000, 1.0990), brk])  # i = 55: k = 4 < i - 50
        self.assertEqual(fractals(at_51, 55)[0], [])
        self.assertIsNone(S.fractal_break(at_51, 55, FRA))

    def test_fractal_mirror_down(self):
        up = mirror(up_bars())
        self.assertEqual(fractals(up, 9), ([2], [6]))  # premise: roles swapped
        s = S.fractal_break(up, 9, FRA)
        self.assertEqual((s["family"], s["side"], s["i"], s["target_raw"], s["detail"]),
                         ("fractal_break", "baissier", 9, None, ""))
        self.assertAlmostEqual(s["stop_raw"], 2.2 - 1.0950, places=12)
        for i in range(0, 9):
            self.assertIsNone(S.fractal_break(up, i, FRA), i)
        # already broken, mirrored
        b = mirror(brk_bars())
        self.assertEqual(fractals(b, 9), ([2], [2, 5]))
        self.assertEqual(S.fractal_break(b[:9], 8, FRA)["side"], "baissier")
        self.assertIsNone(S.fractal_break(b, 9, FRA))
        # ATR stop, mirrored: close + 1.5 x ATR
        g = mirror(gap_bars())
        self.assertEqual(fractals(g, 14), ([2], [7]))
        sg = S.fractal_break(g, 14, FRA)
        self.assertEqual(sg["side"], "baissier")
        self.assertAlmostEqual(sg["stop_raw"], g[14][4] + 1.5 * S.atr_bars(g, 14), places=12)

    def test_fractal_both_directions_gives_none(self):
        # defensive: the geometry makes it unreachable, so force both sides to fire
        bars = up_bars()
        orig = S._fractal_side
        try:
            S._fractal_side = lambda b, i, p, side: S._signal("fractal_break", side, i, 1.0, None)
            self.assertIsNone(S.fractal_break(bars, 9, FRA))
            S._fractal_side = (lambda b, i, p, side:
                               S._signal("fractal_break", side, i, 1.0, None)
                               if side == "haussier" else None)
            self.assertEqual(S.fractal_break(bars, 9, FRA)["side"], "haussier")
        finally:
            S._fractal_side = orig

    def test_fractal_out_of_range_index(self):
        bars = up_bars()
        for i in (-1, 10, 99):
            self.assertIsNone(S.fractal_break(bars, i, FRA))
        self.assertIsNone(S.fractal_break([], 0, FRA))


class ShortAndFlatSeriesTests(unittest.TestCase):
    def test_short_series_give_none_for_both(self):
        # premise: the full fixtures do signal
        eng, up = obars(BULL_ENG), up_bars()
        self.assertIsNotNone(S.engulfing(eng, 4, ENG))
        self.assertIsNotNone(S.fractal_break(up, 9, FRA))
        # every truncation stops before the signalling bar, whatever index is asked
        for bars in (eng, obars(BEAR_ENG), up, gap_bars(), rising_bars()):
            for n in range(0, len(bars)):
                for i in range(-2, n + 3):
                    self.assertIsNone(S.engulfing(bars[:n], i, ENG), (n, i))
                    self.assertIsNone(S.fractal_break(bars[:n], i, FRA), (n, i))
        self.assertIsNone(S.engulfing([], 0, ENG))
        self.assertIsNone(S.fractal_break([], 0, FRA))
        self.assertIsNone(S.fractal_break(obars(BULL_ENG), 4, FRA))  # 5 bars, no fractal

    def test_flat_series_give_no_signal(self):
        f = flat(60)
        for i in range(0, 60):
            self.assertIsNone(S.engulfing(f, i, ENG), i)
            self.assertIsNone(S.fractal_break(f, i, FRA), i)


class DetectAllTests(unittest.TestCase):
    def test_real_families_in_priority_order(self):
        rows = [(1.1000, 1.1010, 1.0990, 1.1005),   # 08:00 range bar
                (1.1010, 1.1012, 1.0995, 1.1000),   # 08:15 range bar, bearish
                (1.1008, 1.1009, 1.1003, 1.1004),   # 08:30 bearish, inside
                (1.1006, 1.1007, 1.1001, 1.1002),   # 08:45 bearish, inside
                (1.1001, 1.1022, 1.1000, 1.1020)]   # 09:00 bullish engulfing, breaks 1.1012
        bars = obars(rows)
        params = dict(SIG_PARAMS, **ENG, range_minutes=30, break_window_hours=3,
                      families=list(S.FAMILIES))
        ranges = S.session_ranges(bars, utc(2026, 11, 16, 16), params)
        sb = S.session_break(bars, 4, ranges, params)
        en = S.engulfing(bars, 4, params)
        self.assertIsNotNone(sb)  # premise
        self.assertIsNotNone(en)
        got = S.detect_all(bars, 4, ranges, params)
        self.assertEqual(got, [sb, en])
        self.assertEqual([s["family"] for s in got], ["session_break", "engulfing"])
        # params["families"] filters, and its own order does not matter
        only = dict(params, families=["engulfing"])
        self.assertEqual(S.detect_all(bars, 4, ranges, only), [en])
        swapped = dict(params, families=["engulfing", "session_break"])
        self.assertEqual(S.detect_all(bars, 4, ranges, swapped), [sb, en])
        none = dict(params, families=["rsi_exit", "bb_return"])
        self.assertEqual(S.detect_all(bars, 4, ranges, none), [])
        self.assertEqual(S.detect_all(bars, 4, ranges, dict(params, families=[])), [])
        self.assertEqual(S.detect_all(bars, 3, ranges, params), [])  # nothing fires at bar 3

    def test_detect_all_orders_by_family_priority_and_honours_params_families(self):
        calls = []
        names = ("session_break", "bb_return", "fractal_break", "engulfing", "rsi_exit")
        saved = {n: getattr(S, n) for n in names}

        def fake(name, result=True):
            def f(*args):
                calls.append((name, args))
                return {"family": name, "side": "haussier", "i": args[1]} if result else None
            return f

        try:
            for n in names:
                setattr(S, n, fake(n, result=(n != "bb_return")))
            bars, ranges = ["bars"], ["ranges"]
            params = {"families": list(reversed(names))}  # deliberately reversed
            got = S.detect_all(bars, 7, ranges, params)
            self.assertEqual([s["family"] for s in got],
                             ["session_break", "fractal_break", "engulfing", "rsi_exit"])
            self.assertEqual([c[0] for c in calls], list(names))  # called in FAMILIES order
            args = dict(calls)
            self.assertEqual(args["session_break"], (bars, 7, ranges, params))
            for n in ("bb_return", "fractal_break", "engulfing", "rsi_exit"):
                self.assertEqual(args[n], (bars, 7, params), n)
            calls.clear()
            got = S.detect_all(bars, 7, ranges, {"families": ["rsi_exit", "fractal_break"]})
            self.assertEqual([s["family"] for s in got], ["fractal_break", "rsi_exit"])
            self.assertEqual([c[0] for c in calls], ["fractal_break", "rsi_exit"])
        finally:
            for n, f in saved.items():
                setattr(S, n, f)


if __name__ == "__main__":
    unittest.main()
