import _path  # noqa
import random
import unittest

import sizing

CAPITAL = 100000
RISK_PCT = 0.5
LEV = 30

KEYS = {"status", "lots", "units", "size", "risk_usd", "leverage",
        "pip_value_usd_per_lot", "limited_by", "note"}


def fx(symbol, entry, stop, prices, capital=CAPITAL, risk_pct=RISK_PCT, lev=LEV):
    return sizing.size_forex(symbol, entry, stop, prices, capital, risk_pct, lev)


class TestHelpers(unittest.TestCase):
    def test_pip_size(self):
        self.assertEqual(sizing.pip_size("JPY"), 0.01)
        self.assertEqual(sizing.pip_size("USD"), 0.0001)

    def test_usd_rate(self):
        self.assertEqual(sizing.usd_rate("USD", {}), 1.0)
        self.assertAlmostEqual(sizing.usd_rate("JPY", {"USDJPY=X": 150.0}), 1 / 150.0)
        self.assertEqual(sizing.usd_rate("EUR", {"EURUSD=X": 1.10}), 1.10)
        self.assertIsNone(sizing.usd_rate("ZAR", {"EURUSD=X": 1.10}))

    def test_usd_rate_prefers_usd_base_pair(self):
        self.assertAlmostEqual(sizing.usd_rate("CHF", {"USDCHF=X": 0.5, "CHFUSD=X": 9.0}), 2.0)

    def test_zero_or_negative_price_is_missing(self):
        self.assertIsNone(sizing.usd_rate("CHF", {"USDCHF=X": 0}))
        self.assertIsNone(sizing.usd_rate("CHF", {"USDCHF=X": -1.0}))
        self.assertEqual(sizing.usd_rate("CHF", {"USDCHF=X": 0, "CHFUSD=X": 1.1}), 1.1)


class TestForex(unittest.TestCase):
    def test_eurusd_50_pips(self):
        s = fx("EURUSD=X", 1.1000, 1.0950, {"EURUSD=X": 1.10})
        self.assertEqual(set(s), KEYS)
        self.assertEqual(s["status"], "ok")
        self.assertEqual(s["units"], 100000)
        self.assertIsInstance(s["units"], int)
        self.assertEqual(s["lots"], 1.0)
        self.assertEqual(s["risk_usd"], 500.0)
        self.assertEqual(s["leverage"], 1.10)
        self.assertEqual(s["pip_value_usd_per_lot"], 10.0)
        self.assertEqual(s["limited_by"], "risque")
        self.assertIsNone(s["size"])
        self.assertIsNone(s["note"])

    def test_usdjpy(self):
        s = fx("USDJPY=X", 150.00, 149.25, {"USDJPY=X": 150.0})
        self.assertEqual(s["status"], "ok")
        self.assertEqual(s["lots"], 1.0)
        self.assertAlmostEqual(s["pip_value_usd_per_lot"], 6.6667, 4)
        self.assertEqual(s["leverage"], 1.0)

    def test_cross_converted_through_a_dollar_pair_and_float_floor(self):
        prices = {"GBPCHF=X": 1.10, "USDCHF=X": 0.88, "GBPUSD=X": 1.30}
        s = fx("GBPCHF=X", 1.1000, 1.0950, prices)
        self.assertEqual(s["status"], "ok")
        self.assertEqual(s["units"], 88000)
        self.assertEqual(s["lots"], 0.88)

    def test_leverage_cap_reduces_the_size(self):
        s = fx("EURUSD=X", 1.1000, 1.0999, {"EURUSD=X": 1.10})
        self.assertEqual(s["status"], "ok")
        self.assertEqual(s["limited_by"], "levier")
        self.assertEqual(s["units"], 2727000)
        self.assertAlmostEqual(s["risk_usd"], 272.7, 2)
        self.assertLess(s["risk_usd"], 500.0)
        self.assertLessEqual(s["leverage"], 30)

    def test_stop_too_wide(self):
        s = fx("EURUSD=X", 2.0, 1.0, {"EURUSD=X": 1.10})
        self.assertEqual(set(s), KEYS)
        self.assertEqual(s["status"], "too_wide")
        self.assertIsNone(s["lots"])
        self.assertIsNone(s["units"])
        self.assertIsNone(s["risk_usd"])
        self.assertIsNone(s["limited_by"])
        self.assertEqual(s["note"], "stop trop large pour le risque fixé")

    def test_rounds_down_never_up(self):
        # raw size: 500 / 0.00500005 = 99 999.0 units
        s = fx("EURUSD=X", 1.1, 1.1 - 0.00500005, {"EURUSD=X": 1.10})
        self.assertEqual(s["units"], 99000)
        self.assertEqual(s["lots"], 0.99)

    def test_unknown_conversion_is_to_confirm(self):
        s = fx("GBPZAR=X", 23.0, 22.5, {"GBPUSD=X": 1.30})
        self.assertEqual(s["status"], "to_confirm")
        self.assertEqual(set(s), KEYS)
        self.assertIsNone(s["units"])
        self.assertIsNone(s["lots"])
        self.assertEqual(s["note"],
                         "conversion de devise impossible : taux en USD introuvable pour ZAR")

    def test_unknown_base_conversion_is_to_confirm(self):
        s = fx("ZARUSD=X", 0.05, 0.049, {})
        self.assertEqual(s["status"], "to_confirm")
        self.assertIn("ZAR", s["note"])

    def test_zero_distance_is_to_confirm_not_an_error(self):
        s = fx("EURUSD=X", 1.1, 1.1, {"EURUSD=X": 1.10})
        self.assertEqual(s["status"], "to_confirm")
        self.assertEqual(s["note"], "distance au stop nulle")
        self.assertIsNone(s["units"])

    def test_distance_uses_absolute_value(self):
        up = fx("EURUSD=X", 1.0950, 1.1000, {"EURUSD=X": 1.10})
        down = fx("EURUSD=X", 1.1000, 1.0950, {"EURUSD=X": 1.10})
        self.assertEqual(up["units"], down["units"])

    def test_real_risk_never_exceeds_the_budget(self):
        rng = random.Random(20261114)
        pairs = {
            "EURUSD=X": (1.10, 0.002, 0.03, {"EURUSD=X": 1.10}),
            "USDJPY=X": (150.0, 0.2, 3.0, {"USDJPY=X": 150.0}),
            "GBPCHF=X": (1.10, 0.002, 0.03,
                         {"GBPCHF=X": 1.10, "USDCHF=X": 0.88, "GBPUSD=X": 1.30}),
        }
        ok_count = 0
        for i in range(40):
            symbol = list(pairs)[i % 3]
            base, lo, hi, prices = pairs[symbol]
            entry = round(base * (1 + rng.uniform(-0.02, 0.02)), 5)
            dist = rng.uniform(lo, hi) * (1 if rng.random() < 0.5 else -1)
            stop = round(entry - dist, 5)
            s = fx(symbol, entry, stop, prices)
            if s["status"] != "ok":
                continue
            ok_count += 1
            self.assertLessEqual(s["risk_usd"], 500.0)
            self.assertEqual(s["units"] % 1000, 0)
            self.assertLessEqual(s["leverage"], 30)
            quote = symbol[3:6]
            q2u = sizing.usd_rate(quote, prices)
            exact = s["units"] * abs(entry - stop) * q2u
            self.assertLessEqual(exact, 500.0 * (1 + 1e-9))
        self.assertGreater(ok_count, 20)

    def test_all_sized_dicts_have_the_nine_keys(self):
        for s in (fx("EURUSD=X", 1.1, 1.095, {"EURUSD=X": 1.10}),
                  fx("EURUSD=X", 2.0, 1.0, {"EURUSD=X": 1.10}),
                  fx("EURUSD=X", 1.1, 1.1, {})):
            self.assertEqual(set(s), KEYS)


CONTRACT = {"usd_per_point": 1.1, "step": 0.1, "min": 0.1}


class TestContract(unittest.TestCase):
    def test_contract_table(self):
        s = sizing.size_contract("^FCHI", 8000, 7900, CONTRACT, CAPITAL, RISK_PCT, LEV)
        self.assertEqual(set(s), KEYS)
        self.assertEqual(s["status"], "ok")
        self.assertEqual(s["size"], 4.5)
        self.assertEqual(s["risk_usd"], 495.0)
        self.assertAlmostEqual(s["leverage"], 0.396, 3)
        self.assertEqual(s["limited_by"], "risque")
        self.assertIsNone(s["lots"])
        self.assertIsNone(s["units"])
        self.assertIsNone(s["pip_value_usd_per_lot"])

    def test_contract_below_min_is_too_wide(self):
        s = sizing.size_contract("^FCHI", 8000, 2000, CONTRACT, CAPITAL, RISK_PCT, LEV)
        self.assertEqual(s["status"], "too_wide")
        self.assertIsNone(s["size"])
        self.assertEqual(s["note"], "stop trop large pour le risque fixé")

    def test_contract_leverage_cap(self):
        c = {"usd_per_point": 1.0, "step": 0.1, "min": 0.1}
        s = sizing.size_contract("^GSPC", 5000, 4999, c, CAPITAL, RISK_PCT, LEV)
        # 1-point stop: value 2.5M stays under the 3M cap, risk decides
        self.assertEqual(s["limited_by"], "risque")
        s = sizing.size_contract("^GSPC", 5000, 4999.9, c, CAPITAL, RISK_PCT, LEV)
        self.assertEqual(s["limited_by"], "levier")
        self.assertEqual(s["size"], 600.0)
        self.assertLessEqual(s["leverage"], 30)
        self.assertLess(s["risk_usd"], 500.0)

    def test_contract_leverage_cap_below_min(self):
        c = {"usd_per_point": 1.0, "step": 1.0, "min": 10.0}
        s = sizing.size_contract("X", 1000000, 999999.9, c, 1000, 0.5, 1)
        self.assertEqual(s["status"], "too_wide")
        self.assertEqual(s["note"], "levier maximum atteint avant la taille minimale")

    def test_contract_zero_distance(self):
        s = sizing.size_contract("^FCHI", 8000, 8000, CONTRACT, CAPITAL, RISK_PCT, LEV)
        self.assertEqual(s["status"], "to_confirm")
        self.assertEqual(s["note"], "distance au stop nulle")

    def test_size_never_rounds_up(self):
        c = {"usd_per_point": 1.0, "step": 0.1, "min": 0.1}
        # raw size 500 / 1.0 / 7.69 = 65.02..., floor to 65.0
        s = sizing.size_contract("X", 100.0, 100.0 - 7.69, c, CAPITAL, RISK_PCT, LEV)
        self.assertEqual(s["size"], 65.0)
        self.assertLessEqual(s["risk_usd"], 500.0)


class TestSizeIdea(unittest.TestCase):
    def cfg(self, contracts=None):
        import config
        c = config.defaults()
        if contracts:
            c["contracts"] = contracts
        return c

    def test_forex_dispatch(self):
        s = sizing.size_idea("EURUSD=X", 1.1000, 1.0950, {"EURUSD=X": 1.10}, self.cfg())
        self.assertEqual(s["status"], "ok")
        self.assertEqual(s["lots"], 1.0)

    def test_contract_dispatch(self):
        s = sizing.size_idea("^FCHI", 8000, 7900, {}, self.cfg({"^FCHI": CONTRACT}))
        self.assertEqual(s["size"], 4.5)

    def test_symbol_without_contract_is_to_confirm(self):
        s = sizing.size_idea("GC=F", 2000, 1990, {}, self.cfg())
        self.assertEqual(s["status"], "to_confirm")
        self.assertEqual(set(s), KEYS)
        self.assertIn("à confirmer chez le courtier", s["note"])
        self.assertEqual(s["note"],
                         "taille à confirmer chez le courtier : renseigner contracts "
                         "dans trader/fx/config.json")

    def test_reads_capital_risk_and_leverage_from_config(self):
        c = self.cfg()
        c["account"]["capital"] = 200000
        c["risk"]["per_trade_pct"] = 1.0
        s = sizing.size_idea("EURUSD=X", 1.1000, 1.0950, {"EURUSD=X": 1.10}, c)
        self.assertEqual(s["units"], 400000)
        self.assertEqual(s["risk_usd"], 2000.0)


if __name__ == "__main__":
    unittest.main()
