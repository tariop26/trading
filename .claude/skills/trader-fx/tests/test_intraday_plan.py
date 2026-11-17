import _path  # noqa
import unittest
from unittest import mock

import config as cfgmod
import intraday_plan as P
import intraday_signals
from intraday_helpers import make_bars, utc

PARAMS = {"min_stop_pct": 0.05, "max_stop_daily_atr": 1.0, "min_rr": 1.0,
          "validity_r": 0.25, "target_r": 2.0, "stop_atr_mult": 1.5}
EUR = "EURUSD=X"


class MakeSignalPlanTests(unittest.TestCase):
    def test_long_with_range_stop_and_2r_target(self):
        got = P.make_signal_plan(EUR, "haussier", 1.10200, 1.09900, None, 0.0070, PARAMS)
        self.assertEqual(got, ({"reference_price": 1.102, "stop": 1.099, "target": 1.108,
                                "rr": 2.0, "decimals": 5, "limit_price": 1.10275}, None))

    def test_short_mirror(self):
        got = P.make_signal_plan(EUR, "baissier", 1.10200, 1.10500, None, 0.0070, PARAMS)
        self.assertEqual(got, ({"reference_price": 1.102, "stop": 1.105, "target": 1.096,
                                "rr": 2.0, "decimals": 5, "limit_price": 1.10125}, None))

    def test_stop_is_rounded_away_from_the_entry(self):
        got, why = P.make_signal_plan(EUR, "haussier", 1.10200, 1.098996, None, 0.0070, PARAMS)
        self.assertIsNone(why)
        self.assertEqual(got["stop"], 1.09899)      # down, not 1.09900
        got, why = P.make_signal_plan(EUR, "baissier", 1.10200, 1.105004, None, 0.0070, PARAMS)
        self.assertIsNone(why)
        self.assertEqual(got["stop"], 1.10501)      # up, not 1.10500

    def test_target_raw_is_used_and_rounded_toward_entry(self):
        got = P.make_signal_plan(EUR, "haussier", 1.10200, 1.09900, 1.105604, 0.0070, PARAMS)
        self.assertEqual(got, ({"reference_price": 1.102, "stop": 1.099, "target": 1.1056,
                                "rr": 1.2, "decimals": 5, "limit_price": 1.10275}, None))
        got = P.make_signal_plan(EUR, "baissier", 1.10200, 1.10500, 1.098396, 0.0070, PARAMS)
        self.assertEqual(got, ({"reference_price": 1.102, "stop": 1.105, "target": 1.0984,
                                "rr": 1.2, "decimals": 5, "limit_price": 1.10125}, None))

    def test_jpy_pair_uses_three_decimals(self):
        got = P.make_signal_plan("USDJPY=X", "haussier", 150.250, 149.9004, None, 0.8, PARAMS)
        self.assertEqual(got, ({"reference_price": 150.25, "stop": 149.9, "target": 150.95,
                                "rr": 2.0, "decimals": 3, "limit_price": 150.337}, None))

    def test_stop_too_close_rejected(self):
        # 0.00033 / 1.102 = 0.03 %
        got = P.make_signal_plan(EUR, "haussier", 1.10200, 1.10167, None, 0.0070, PARAMS)
        self.assertEqual(got, (None, "stop trop proche"))

    def test_stop_too_wide_rejected(self):
        # 0.0105 = 1.5 daily ATR
        got = P.make_signal_plan(EUR, "haussier", 1.10200, 1.09150, None, 0.0070, PARAMS)
        self.assertEqual(got, (None, "stop trop large"))

    def test_stop_exactly_at_the_limits_is_accepted(self):
        # dist 0.007 == 1.0 daily ATR
        got, why = P.make_signal_plan(EUR, "haussier", 1.10200, 1.09500, None, 0.0070, PARAMS)
        self.assertIsNone(why)
        self.assertEqual(got["stop"], 1.095)

    def test_rr_below_minimum_rejected(self):
        # target at 0.5 R
        got = P.make_signal_plan(EUR, "haussier", 1.10200, 1.09900, 1.10350, 0.0070, PARAMS)
        self.assertEqual(got, (None, "rapport 1:R sous le minimum"))

    def test_wrong_side_target_is_impossible(self):
        got = P.make_signal_plan(EUR, "haussier", 1.10200, 1.09900, 1.10000, 0.0070, PARAMS)
        self.assertEqual(got, (None, "plan impossible"))
        got = P.make_signal_plan(EUR, "baissier", 1.10200, 1.10500, 1.10400, 0.0070, PARAMS)
        self.assertEqual(got, (None, "plan impossible"))

    def test_wrong_side_or_null_stop_is_impossible(self):
        got = P.make_signal_plan(EUR, "haussier", 1.10200, 1.10500, None, 0.0070, PARAMS)
        self.assertEqual(got, (None, "plan impossible"))
        # stop rounds onto the entry: no division by zero
        got = P.make_signal_plan(EUR, "haussier", 1.10200, 1.102, None, 0.0070, PARAMS)
        self.assertEqual(got, (None, "plan impossible"))

    def test_non_finite_inputs_are_impossible(self):
        nan, inf = float("nan"), float("inf")
        for close, stop, target in ((nan, 1.099, None), (1.102, inf, None),
                                    (1.102, 1.099, nan), (1.102, None, None),
                                    ("1.102", 1.099, None), (None, 1.099, None)):
            got = P.make_signal_plan(EUR, "haussier", close, stop, target, 0.0070, PARAMS)
            self.assertEqual(got, (None, "plan impossible"), (close, stop, target))

    def test_missing_or_zero_daily_atr(self):
        nan = float("nan")
        for atr in (None, 0, 0.0, -0.007, nan, float("inf")):
            got = P.make_signal_plan(EUR, "haussier", 1.10200, 1.09900, None, atr, PARAMS)
            self.assertEqual(got, (None, "ATR journalier indisponible"), atr)

    def test_atr_checked_before_the_inputs(self):
        got = P.make_signal_plan(EUR, "haussier", float("nan"), 1.099, None, None, PARAMS)
        self.assertEqual(got, (None, "ATR journalier indisponible"))

    def test_gold_and_index_use_magnitude_decimals(self):
        got = P.make_signal_plan("GC=F", "haussier", 2650.40, 2640.123, None, 30.0, PARAMS)
        self.assertEqual(got, ({"reference_price": 2650.4, "stop": 2640.12, "target": 2670.96,
                                "rr": 2.0, "decimals": 2, "limit_price": 2652.97}, None))
        got = P.make_signal_plan("^FCHI", "baissier", 7500.5, 7520.123, None, 100.0, PARAMS)
        self.assertEqual(got, ({"reference_price": 7500.5, "stop": 7520.13, "target": 7461.24,
                                "rr": 2.0, "decimals": 2, "limit_price": 7495.6}, None))


BAR_S = 900
LONG, SHORT = "haussier", "baissier"
NOW = utc(2026, 11, 16, 10, 0)
CTX_UP = {"name": "Euro / Dollar", "last": 1.10, "atr_pct": 0.64, "trend": "up"}


def sig(family, side, i, stop=1.0990, target=None, detail=""):
    return {"family": family, "side": side, "i": i, "stop_raw": stop,
            "target_raw": target, "detail": detail}


def flat_bars(n=10, close=1.1020, start=None):
    """n bars; by default the last one starts 09:45 and closes 10:00 (= NOW)."""
    t0 = int(start if start is not None else NOW.timestamp() - n * BAR_S)
    return [(t0 + k * BAR_S, close, close + 0.0005, close - 0.0005, close) for k in range(n)]


def fake_detect(by_i):
    def detect(bars, i, ranges, params):
        return [dict(s) for s in by_i.get(i, [])]
    return detect


def scan(by_i, ctx=CTX_UP, symbol=EUR, bars=None, config=None, prices=None, now=NOW,
         name="Euro / Dollar"):
    config = config or cfgmod.defaults()
    bars = bars if bars is not None else flat_bars()
    prices = prices if prices is not None else {EUR: 1.10}
    with mock.patch.object(intraday_signals, "detect_all", side_effect=fake_detect(by_i)):
        return P.scan_symbol(symbol, name, bars, [], ctx, config, prices, now)


class ScoreTests(unittest.TestCase):
    def test_single_signal_scores_2_plus_trend(self):
        by_i = {9: [sig("session_break", LONG, 9, detail="Londres")]}
        cand, why = scan(by_i)
        self.assertIsNone(why)
        self.assertEqual(cand["score"], 3)
        self.assertEqual(cand["why"], ["+2 session_break (Londres)", "+1 tendance haussière"])
        self.assertEqual(cand["families"], ["session_break"])
        self.assertEqual(cand["primary"], "session_break")
        self.assertEqual(cand["detail"], "Londres")

    def test_trend_against_subtracts(self):
        by_i = {9: [sig("session_break", LONG, 9, detail="Londres")]}
        cand, why = scan(by_i, ctx=dict(CTX_UP, trend="down"))
        self.assertIsNone(why)
        self.assertEqual(cand["score"], 1)
        self.assertEqual(cand["why"], ["+2 session_break (Londres)",
                                       "−1 tendance baissière (à contre-sens)"])

    def test_short_with_down_trend_adds(self):
        by_i = {9: [sig("engulfing", SHORT, 9, stop=1.1050)]}
        cand, why = scan(by_i, ctx=dict(CTX_UP, trend="down"))
        self.assertIsNone(why)
        self.assertEqual(cand["score"], 3)
        self.assertEqual(cand["why"], ["+2 engulfing", "+1 tendance baissière"])

    def test_mixed_missing_or_none_trend_adds_nothing(self):
        by_i = {9: [sig("session_break", LONG, 9, detail="Londres")]}
        for ctx in (dict(CTX_UP, trend="mixed"), dict(CTX_UP, trend=None),
                    {"name": "x", "last": 1.10, "atr_pct": 0.64}):
            cand, why = scan(by_i, ctx=ctx)
            self.assertIsNone(why)
            self.assertEqual(cand["score"], 2, ctx)
            self.assertEqual(cand["why"], ["+2 session_break (Londres)"])

    def test_two_concordant_families_score_4_and_list_both(self):
        by_i = {7: [sig("session_break", LONG, 7, detail="Londres")],
                9: [sig("bb_return", LONG, 9, target=1.1080)]}
        cand, why = scan(by_i, ctx=dict(CTX_UP, trend="mixed"))
        self.assertIsNone(why)
        self.assertEqual(cand["score"], 4)
        self.assertEqual(cand["families"], ["session_break", "bb_return"])
        self.assertEqual(cand["primary"], "bb_return")      # the one on the newest bar
        self.assertEqual(cand["why"], ["+2 session_break (Londres)", "+2 bb_return"])
        self.assertEqual(cand["bar_ts"], flat_bars()[9][0])

    def test_primary_is_highest_priority_on_the_newest_bar(self):
        by_i = {9: [sig("fractal_break", LONG, 9, detail="x"), sig("engulfing", LONG, 9)]}
        cand, why = scan(by_i)
        self.assertIsNone(why)
        self.assertEqual(cand["primary"], "fractal_break")
        self.assertEqual(cand["detail"], "x")
        self.assertEqual(cand["families"], ["fractal_break", "engulfing"])

    def test_same_family_twice_counts_once(self):
        by_i = {8: [sig("engulfing", LONG, 8)], 9: [sig("engulfing", LONG, 9)]}
        cand, why = scan(by_i, ctx=dict(CTX_UP, trend="mixed"))
        self.assertIsNone(why)
        self.assertEqual(cand["score"], 2)
        self.assertEqual(cand["families"], ["engulfing"])

    def test_opposite_signal_in_window_cancels(self):
        by_i = {7: [sig("session_break", SHORT, 7, stop=1.1050)],
                9: [sig("engulfing", LONG, 9)]}
        self.assertEqual(scan(by_i), (None, "signaux contradictoires"))

    def test_signal_outside_the_window_is_ignored(self):
        # window_bars = 4: indexes 6..9; index 5 is out
        by_i = {5: [sig("session_break", SHORT, 5, stop=1.1050)],
                9: [sig("engulfing", LONG, 9)]}
        cand, why = scan(by_i)
        self.assertIsNone(why)
        self.assertEqual(cand["side"], LONG)
        self.assertEqual(scan({5: [sig("session_break", LONG, 5)]}),
                         (None, "aucun signal récent"))

    def test_no_signal_returns_no_recent_signal(self):
        self.assertEqual(scan({}), (None, "aucun signal récent"))


class StalenessTests(unittest.TestCase):
    def _bars_closed_minutes_ago(self, minutes):
        end = NOW.timestamp() - minutes * 60          # close of the last bar
        return flat_bars(10, start=end - 10 * BAR_S)

    def test_signal_older_than_30_minutes_is_stale(self):
        bars = self._bars_closed_minutes_ago(31)
        self.assertEqual(bars[-1][0] + BAR_S, NOW.timestamp() - 31 * 60)
        by_i = {9: [sig("engulfing", LONG, 9)]}
        self.assertEqual(scan(by_i, bars=bars), (None, "plan caduc"))

    def test_signal_exactly_30_minutes_old_is_accepted(self):
        bars = self._bars_closed_minutes_ago(30)
        self.assertEqual(bars[-1][0] + BAR_S, NOW.timestamp() - 30 * 60)
        by_i = {9: [sig("engulfing", LONG, 9)]}
        cand, why = scan(by_i, bars=bars)
        self.assertIsNone(why)
        self.assertEqual(cand["bar_ts"], bars[9][0])

    def test_staleness_uses_the_newest_signal_bar(self):
        # newest signal on bar 6, closed 45 min before NOW (bar 7 closed 30 min before)
        by_i = {6: [sig("engulfing", LONG, 6)]}
        self.assertEqual(scan(by_i), (None, "plan caduc"))

    def test_stale_checked_before_contradiction(self):
        by_i = {6: [sig("engulfing", SHORT, 6, stop=1.1050), sig("rsi_exit", LONG, 6)]}
        self.assertEqual(scan(by_i), (None, "plan caduc"))

    def test_unclosed_bar_is_never_read(self):
        bars = flat_bars() + [(int(NOW.timestamp()) - 300, 1.1, 1.2, 1.0, 1.1)]
        seen = []

        def detect(b, i, ranges, params):
            seen.append(len(b))
            return []
        with mock.patch.object(intraday_signals, "detect_all", side_effect=detect):
            got = P.scan_symbol(EUR, "x", bars, [], CTX_UP, cfgmod.defaults(), {}, NOW)
        self.assertEqual(got, (None, "aucun signal récent"))
        self.assertEqual(set(seen), {10})


class PlanAndSizeTests(unittest.TestCase):
    def test_plan_rejection_reason_is_propagated(self):
        # stop 0.0003 away = 0.027 % of the entry, under min_stop_pct
        got = scan({9: [sig("engulfing", LONG, 9, stop=1.1017)]})
        self.assertEqual(got, (None, "stop trop proche"))
        got = scan({9: [sig("engulfing", LONG, 9, stop=1.0900)]})
        self.assertEqual(got, (None, "stop trop large"))

    def test_missing_daily_atr_gives_a_reason(self):
        by_i = {9: [sig("engulfing", LONG, 9)]}
        for ctx in (None, {}, dict(CTX_UP, atr_pct=None), dict(CTX_UP, atr_pct=0),
                    dict(CTX_UP, last=True), dict(CTX_UP, atr_pct=float("nan"))):
            self.assertEqual(scan(by_i, ctx=ctx), (None, "ATR journalier indisponible"), ctx)

    def test_flat_series_gives_no_candidate_without_error(self):
        bars = [(t, 1.1, 1.1, 1.1, 1.1) for t, *_ in flat_bars(30)]   # zero true range
        got = P.scan_symbol(EUR, "x", bars, [], CTX_UP, cfgmod.defaults(), {EUR: 1.1}, NOW)
        self.assertEqual(got, (None, "aucun signal récent"))
        # a zero daily ATR as well, even with a signal
        by_i = {29: [sig("engulfing", LONG, 29, stop=1.0990)]}
        got = scan(by_i, ctx=dict(CTX_UP, atr_pct=0.0), bars=bars)
        self.assertEqual(got, (None, "ATR journalier indisponible"))

    def test_gold_without_contract_keeps_candidate_with_to_confirm_size(self):
        config = cfgmod.defaults()
        self.assertNotIn("GC=F", config["contracts"])
        bars = flat_bars(10, close=2650.40)
        by_i = {9: [sig("engulfing", LONG, 9, stop=2640.0)]}
        ctx = {"name": "Or", "last": 2650.0, "atr_pct": 1.2, "trend": "up"}
        cand, why = scan(by_i, ctx=ctx, symbol="GC=F", bars=bars, config=config, name="Or")
        self.assertIsNone(why)
        self.assertEqual(cand["plan"]["reference_price"], 2650.4)
        self.assertEqual(cand["size"]["status"], "to_confirm")
        self.assertIsNone(cand["size"]["lots"])
        self.assertEqual(cand["exposures"], [("GC=F", "+")])

    def test_arithmetic_error_refuses_the_symbol_alone(self):
        by_i = {9: [sig("engulfing", LONG, 9)]}
        with mock.patch.object(P.plan, "exposures", side_effect=ZeroDivisionError):
            got = scan(by_i)
        self.assertEqual(got, (None, "calcul impossible (ZeroDivisionError)"))

    def test_display_name_uses_mt5_table(self):
        by_i = {9: [sig("engulfing", LONG, 9)]}
        cand, _ = scan(by_i)
        self.assertEqual(cand["display_name"], "Euro / Dollar")
        config = cfgmod.defaults()
        config["intraday"]["mt5_symbols"] = {EUR: "EURUSD.r"}
        cand, _ = scan(by_i, config=config)
        self.assertEqual(cand["display_name"], "EURUSD.r")


class IntegrationTests(unittest.TestCase):
    def test_london_session_break_end_to_end(self):
        config = cfgmod.defaults()
        params = intraday_signals.signal_params(config)
        bars = make_bars(utc(2026, 11, 16, 8, 0), [
            (1.1000, 1.1010, 1.0990, 1.1005),   # 08:00 range
            (1.1005, 1.1010, 1.0995, 1.1000),   # 08:15 range
            (1.1005, 1.1025, 1.1000, 1.1020),   # 08:30 break, close 1.1020
        ])
        now = utc(2026, 11, 16, 8, 45)
        closed = intraday_signals.closed_bars(bars, now)
        self.assertEqual(len(closed), 3)
        ranges = intraday_signals.session_ranges(closed, now, params)
        london = [r for r in ranges if r["name"] == "Londres"]
        self.assertEqual((london[0]["high"], london[0]["low"]), (1.1010, 1.0990))
        self.assertEqual(london[0]["end"], bars[2][0])
        got = intraday_signals.detect_all(closed, 2, ranges, params)
        self.assertEqual([s["family"] for s in got], ["session_break"])
        self.assertEqual(got[0]["stop_raw"], 1.0990)

        cand, why = P.scan_symbol(EUR, "Euro / Dollar", bars, ranges, CTX_UP, config,
                                  {EUR: 1.10}, now)
        self.assertIsNone(why)
        self.assertEqual(cand["symbol"], EUR)
        self.assertEqual(cand["side"], LONG)
        self.assertEqual(cand["score"], 3)
        self.assertEqual(cand["why"], ["+2 session_break (Londres)", "+1 tendance haussière"])
        self.assertEqual(cand["families"], ["session_break"])
        self.assertEqual(cand["primary"], "session_break")
        self.assertEqual(cand["detail"], "Londres")
        self.assertEqual(cand["bar_ts"], bars[2][0])
        self.assertEqual(cand["bar_iso"], "2026-11-16T08:30:00+00:00")
        self.assertEqual(cand["plan"], {"reference_price": 1.102, "stop": 1.099,
                                        "target": 1.108, "rr": 2.0, "decimals": 5,
                                        "limit_price": 1.10275})
        self.assertEqual(cand["exposures"], [("EUR", "+"), ("USD", "-")])
        self.assertNotEqual(cand["size"]["status"], "to_confirm")
        self.assertIsNotNone(cand["size"]["lots"])


if __name__ == "__main__":
    unittest.main()
