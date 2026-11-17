import _path  # noqa
import unittest

import intraday_plan as P

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


if __name__ == "__main__":
    unittest.main()
