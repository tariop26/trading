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


if __name__ == "__main__":
    unittest.main()
